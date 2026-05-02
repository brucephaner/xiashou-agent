"""Regression tests for ContextVar propagation into concurrent tool workers."""

from __future__ import annotations

import ast
import concurrent.futures
import contextvars
import inspect
from types import SimpleNamespace


def test_executor_submit_without_copy_context_does_not_propagate():
    probe: contextvars.ContextVar[str] = contextvars.ContextVar(
        "probe_default_propagation",
        default="unset",
    )
    probe.set("set-in-main")

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
        observed = executor.submit(probe.get).result(timeout=5)

    assert observed == "unset"


def test_executor_submit_with_copy_context_run_propagates():
    probe: contextvars.ContextVar[str] = contextvars.ContextVar(
        "probe_explicit_propagation",
        default="unset",
    )
    probe.set("set-in-main")

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
        ctx = contextvars.copy_context()
        observed = executor.submit(ctx.run, probe.get).result(timeout=5)

    assert observed == "set-in-main"


def test_run_agent_concurrent_executor_wraps_submit_with_copy_context():
    import run_agent

    src_path = inspect.getsourcefile(run_agent)
    assert src_path is not None
    tree = ast.parse(open(src_path, encoding="utf-8").read())

    tool_submits = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not isinstance(func, ast.Attribute) or func.attr != "submit":
            continue
        if not node.args:
            continue
        first = node.args[0]
        if isinstance(first, ast.Name) and first.id == "_run_tool":
            tool_submits.append(("unfixed", node))
        elif (
            isinstance(first, ast.Attribute)
            and first.attr == "run"
            and len(node.args) >= 2
            and isinstance(node.args[1], ast.Name)
            and node.args[1].id == "_run_tool"
        ):
            tool_submits.append(("fixed", node))

    assert tool_submits, "could not locate concurrent _run_tool submit call"
    assert all(kind == "fixed" for kind, _ in tool_submits)


def test_concurrent_tool_worker_sees_gateway_contextvars(monkeypatch):
    from gateway.session_context import (
        get_session_env,
        reset_context_env_vars,
        set_context_env_vars,
    )
    from run_agent import AIAgent
    from tools.approval import (
        get_current_session_key,
        reset_current_session_key,
        set_current_session_key,
    )

    agent = AIAgent(
        api_key="dummy-key",
        base_url="http://localhost/v1",
        model="test-model",
        quiet_mode=True,
        enabled_toolsets=[],
        skip_context_files=True,
        skip_memory=True,
    )
    observed: list[tuple[str, str]] = []

    def fake_invoke(function_name, function_args, effective_task_id, tool_call_id=None):
        observed.append((
            get_current_session_key(default="missing"),
            get_session_env("HERMES_SESSION_CHAT_ID", "missing"),
        ))
        return "ok"

    monkeypatch.setattr(agent, "_invoke_tool", fake_invoke)
    approval_token = set_current_session_key("session-A")
    session_tokens = set_context_env_vars({
        "HERMES_SESSION_KEY": "session-A",
        "HERMES_SESSION_CHAT_ID": "chat-A",
    })
    try:
        assistant_message = SimpleNamespace(
            tool_calls=[
                SimpleNamespace(
                    id="call-1",
                    function=SimpleNamespace(name="probe", arguments="{}"),
                ),
                SimpleNamespace(
                    id="call-2",
                    function=SimpleNamespace(name="probe", arguments="{}"),
                ),
            ]
        )
        messages = []
        agent._execute_tool_calls_concurrent(assistant_message, messages, "task-1")
    finally:
        reset_context_env_vars(session_tokens)
        reset_current_session_key(approval_token)
        agent.close()

    assert sorted(observed) == [("session-A", "chat-A"), ("session-A", "chat-A")]
    assert [msg["tool_call_id"] for msg in messages] == ["call-1", "call-2"]
