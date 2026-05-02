import asyncio
import inspect

import pytest

from gateway.config import Platform, PlatformConfig
from gateway.platforms.base import BasePlatformAdapter, MessageEvent, SendResult
from gateway.session import SessionSource, build_session_key


class DrainTestAdapter(BasePlatformAdapter):
    def __init__(self):
        super().__init__(PlatformConfig(enabled=True, token="fake"), Platform.TELEGRAM)
        self.sent = []
        self.stop_typing_calls = 0

    async def connect(self):
        return True

    async def disconnect(self):
        return None

    async def send(self, chat_id, content, reply_to=None, metadata=None):
        self.sent.append(content)
        return SendResult(success=True, message_id=str(len(self.sent)))

    async def send_typing(self, chat_id, metadata=None):
        return None

    async def stop_typing(self, chat_id):
        self.stop_typing_calls += 1
        return None

    async def get_chat_info(self, chat_id):
        return {"id": chat_id}


def _make_event(text: str) -> MessageEvent:
    return MessageEvent(
        text=text,
        source=SessionSource(
            platform=Platform.TELEGRAM,
            chat_id="chat-1",
            chat_type="dm",
            user_id="user-1",
        ),
        message_id=text,
    )


async def _wait_for_background_tasks(adapter: DrainTestAdapter) -> None:
    for _ in range(20):
        tasks = [task for task in adapter._background_tasks if not task.done()]
        if not tasks:
            return
        await asyncio.gather(*tasks)
        await asyncio.sleep(0)


@pytest.mark.asyncio
async def test_pending_drain_uses_fresh_tasks_not_recursive_stack():
    adapter = DrainTestAdapter()
    session_key = build_session_key(_make_event("0").source)
    depths = []
    handled = 0
    all_handled = asyncio.Event()

    async def handler(event):
        nonlocal handled
        handled += 1
        depths.append(
            sum(
                1
                for frame in inspect.stack()
                if frame.function == "_process_message_background"
            )
        )
        idx = int(event.text)
        if idx < 11:
            adapter._pending_messages[session_key] = _make_event(str(idx + 1))
            adapter._active_sessions[session_key].set()
        if handled == 12:
            all_handled.set()
        return f"ack {event.text}"

    adapter.set_message_handler(handler)

    await adapter._process_message_background(_make_event("0"), session_key)
    await asyncio.wait_for(all_handled.wait(), timeout=2)
    await _wait_for_background_tasks(adapter)

    assert handled == 12
    assert max(depths) == 1


@pytest.mark.asyncio
async def test_pending_drain_preserves_session_guard_across_handoff():
    adapter = DrainTestAdapter()
    session_key = build_session_key(_make_event("first").source)
    guards = []
    second_seen = asyncio.Event()

    async def handler(event):
        guards.append(adapter._active_sessions[session_key])
        if event.text == "first":
            adapter._pending_messages[session_key] = _make_event("second")
            adapter._active_sessions[session_key].set()
        else:
            second_seen.set()
        return f"ack {event.text}"

    adapter.set_message_handler(handler)

    await adapter._process_message_background(_make_event("first"), session_key)
    await asyncio.wait_for(second_seen.wait(), timeout=2)
    await _wait_for_background_tasks(adapter)

    assert len(guards) == 2
    assert guards[0] is guards[1]


@pytest.mark.asyncio
async def test_late_pending_during_cleanup_is_drained():
    adapter = DrainTestAdapter()
    session_key = build_session_key(_make_event("first").source)
    handled = []
    second_seen = asyncio.Event()

    async def handler(event):
        handled.append(event.text)
        if event.text == "second":
            second_seen.set()
        return f"ack {event.text}"

    async def quiet_typing(_chat_id, interval=2.0, metadata=None):
        await asyncio.Event().wait()

    async def inject_late_pending(_chat_id):
        if "second" not in handled and session_key not in adapter._pending_messages:
            adapter._pending_messages[session_key] = _make_event("second")
            adapter._active_sessions[session_key].set()
        await asyncio.sleep(0)

    adapter.set_message_handler(handler)
    adapter._keep_typing = quiet_typing
    adapter.stop_typing = inject_late_pending

    await adapter._process_message_background(_make_event("first"), session_key)
    await asyncio.wait_for(second_seen.wait(), timeout=2)
    await _wait_for_background_tasks(adapter)

    assert handled == ["first", "second"]
