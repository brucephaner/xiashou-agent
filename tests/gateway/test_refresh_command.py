"""Tests for the managed Weixin /refresh command."""
from unittest.mock import AsyncMock, MagicMock

import pytest
import yaml

import gateway.run as gateway_run
from gateway.config import Platform
from gateway.platforms.base import MessageEvent, MessageType
from gateway.session import SessionSource
from hermes_cli.commands import resolve_command
from tests.gateway.restart_test_helpers import make_restart_runner


def _make_weixin_event(text: str = "/刷新") -> MessageEvent:
    return MessageEvent(
        text=text,
        message_type=MessageType.TEXT,
        source=SessionSource(
            platform=Platform.WEIXIN,
            chat_id="dm-42",
            chat_type="dm",
            user_id="o9cq802X8p8n6GIzE7JETH-5EvEc@im.wechat",
        ),
        message_id="m1",
    )


def test_refresh_alias_resolves():
    command = resolve_command("/刷新")
    assert command is not None
    assert command.name == "refresh"


@pytest.mark.asyncio
async def test_refresh_command_writes_config_and_applies_without_restart(tmp_path, monkeypatch):
    monkeypatch.setattr(gateway_run, "_hermes_home", tmp_path)
    monkeypatch.setenv("HERMES_MANAGED", "xiashou")
    monkeypatch.delenv("INVOCATION_ID", raising=False)

    runner, _adapter = make_restart_runner()
    runner.request_restart = MagicMock(return_value=True)
    event = _make_weixin_event()
    session_key = runner._session_key_for_source(event.source)
    runner._session_model_overrides[session_key] = {
        "model": "old:model",
        "provider": "old-provider",
    }
    runner._fetch_backend_active_key = AsyncMock(
        return_value={
            "api_key": "sk-test-key",
            "base_url": "https://api.wokey.ai/messages",
            "model": "moonshot:kimi-k2.6",
            "vision_model": "moonshot:kimi-k2.6",
        }
    )
    runner._probe_refresh_key_with_retry = AsyncMock(
        return_value=(False, "请求过于频繁，请稍后再试", True)
    )

    result = await runner._handle_refresh_command(event)

    assert "已更新为 moonshot:kimi-k2.6" in result
    assert "moonshot:kimi-k2.6" in result
    runner.request_restart.assert_not_called()

    config = yaml.safe_load((tmp_path / "config.yaml").read_text(encoding="utf-8"))
    assert config["model"]["default"] == "moonshot:kimi-k2.6"
    provider = config["providers"]["wokey.ai"]
    assert provider["api"] == "https://api.wokey.ai/messages"
    assert provider["api_key"] == "sk-test-key"
    assert provider["models"] == ["moonshot:kimi-k2.6"]
    assert provider["transport"] == "anthropic_messages"
    assert config["auxiliary"]["vision"]["model"] == "moonshot:kimi-k2.6"
    assert session_key not in runner._session_model_overrides


@pytest.mark.asyncio
async def test_refresh_command_returns_error_when_backend_lookup_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(gateway_run, "_hermes_home", tmp_path)
    monkeypatch.setenv("HERMES_MANAGED", "xiashou")

    runner, _adapter = make_restart_runner()
    runner.request_restart = MagicMock(return_value=True)
    runner._fetch_backend_active_key = AsyncMock(return_value=None)

    result = await runner._handle_refresh_command(_make_weixin_event())

    assert "未查询到可用模型配置" in result
    runner.request_restart.assert_not_called()
    assert not (tmp_path / "config.yaml").exists()
