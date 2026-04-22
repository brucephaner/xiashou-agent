"""Tests for session auto-reset notifications.

Verifies that:
- _should_reset() returns a reason string ("idle" or "daily") instead of bool
- SessionEntry captures auto_reset_reason
- Suspend reasons distinguish interrupted restarts from fresh-start resets
- SessionResetPolicy.notify controls whether notifications are sent
- notify_exclude_platforms skips notifications for excluded platforms
"""

import json
from datetime import datetime, timedelta
from unittest.mock import MagicMock

import pytest

from gateway.config import (
    GatewayConfig,
    Platform,
    PlatformConfig,
    SessionResetPolicy,
)
from gateway.session import (
    SUSPEND_REASON_INTERRUPTED_RESTART,
    SUSPEND_REASON_MANUAL_STOP,
    SessionEntry,
    SessionSource,
    SessionStore,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_source(platform=Platform.TELEGRAM, chat_id="123", user_id="u1"):
    return SessionSource(
        platform=platform,
        chat_id=chat_id,
        user_id=user_id,
    )


def _make_store(policy=None, tmp_path=None):
    config = GatewayConfig()
    if policy:
        config.default_reset_policy = policy
    store = SessionStore(sessions_dir=tmp_path or "/tmp/test-sessions", config=config)
    return store


# ---------------------------------------------------------------------------
# _should_reset returns reason string
# ---------------------------------------------------------------------------

class TestShouldResetReason:
    def test_returns_none_when_not_expired(self, tmp_path):
        store = _make_store(
            SessionResetPolicy(mode="both", idle_minutes=60, at_hour=4),
            tmp_path,
        )
        entry = SessionEntry(
            session_key="test",
            session_id="s1",
            created_at=datetime.now(),
            updated_at=datetime.now(),  # just updated
        )
        source = _make_source()
        assert store._should_reset(entry, source) is None

    def test_returns_idle_when_idle_expired(self, tmp_path):
        store = _make_store(
            SessionResetPolicy(mode="idle", idle_minutes=30),
            tmp_path,
        )
        entry = SessionEntry(
            session_key="test",
            session_id="s1",
            created_at=datetime.now() - timedelta(hours=2),
            updated_at=datetime.now() - timedelta(hours=1),  # 60min ago > 30min threshold
        )
        source = _make_source()
        assert store._should_reset(entry, source) == "idle"

    def test_returns_daily_when_daily_boundary_crossed(self, tmp_path):
        now = datetime.now()
        store = _make_store(
            SessionResetPolicy(mode="daily", at_hour=now.hour),
            tmp_path,
        )
        entry = SessionEntry(
            session_key="test",
            session_id="s1",
            created_at=now - timedelta(days=2),
            updated_at=now - timedelta(days=1),  # last active yesterday
        )
        source = _make_source()
        assert store._should_reset(entry, source) == "daily"

    def test_returns_none_when_mode_is_none(self, tmp_path):
        store = _make_store(
            SessionResetPolicy(mode="none"),
            tmp_path,
        )
        entry = SessionEntry(
            session_key="test",
            session_id="s1",
            created_at=datetime.now() - timedelta(days=30),
            updated_at=datetime.now() - timedelta(days=30),
        )
        source = _make_source()
        assert store._should_reset(entry, source) is None


# ---------------------------------------------------------------------------
# SessionEntry captures reason
# ---------------------------------------------------------------------------

class TestSessionEntryReason:
    def test_auto_reset_reason_stored(self, tmp_path):
        store = _make_store(
            SessionResetPolicy(mode="idle", idle_minutes=1),
            tmp_path,
        )
        source = _make_source()

        # Create initial session
        entry1 = store.get_or_create_session(source)
        assert not entry1.was_auto_reset

        # Age it past the idle threshold
        entry1.updated_at = datetime.now() - timedelta(minutes=5)
        store._save()

        # Next call should create a new session with reason
        entry2 = store.get_or_create_session(source)
        assert entry2.was_auto_reset is True
        assert entry2.auto_reset_reason == "idle"
        assert entry2.session_id != entry1.session_id

    def test_reset_had_activity_false_when_no_tokens(self, tmp_path):
        """Expired session with no tokens → reset_had_activity=False."""
        store = _make_store(
            SessionResetPolicy(mode="idle", idle_minutes=1),
            tmp_path,
        )
        source = _make_source()

        entry1 = store.get_or_create_session(source)
        # No tokens used — session was idle with no conversation
        entry1.updated_at = datetime.now() - timedelta(minutes=5)
        store._save()

        entry2 = store.get_or_create_session(source)
        assert entry2.was_auto_reset is True
        assert entry2.reset_had_activity is False

    def test_reset_had_activity_true_when_tokens_used(self, tmp_path):
        """Expired session with tokens → reset_had_activity=True."""
        store = _make_store(
            SessionResetPolicy(mode="idle", idle_minutes=1),
            tmp_path,
        )
        source = _make_source()

        entry1 = store.get_or_create_session(source)
        # Simulate some conversation happened
        entry1.total_tokens = 5000
        entry1.updated_at = datetime.now() - timedelta(minutes=5)
        store._save()

        entry2 = store.get_or_create_session(source)
        assert entry2.was_auto_reset is True
        assert entry2.reset_had_activity is True

    def test_interrupted_restart_preserves_session_and_sets_resume_notice(self, tmp_path):
        store = _make_store(
            SessionResetPolicy(mode="none"),
            tmp_path,
        )
        source = _make_source()

        entry1 = store.get_or_create_session(source)
        original_session_id = entry1.session_id

        assert store.suspend_recently_active() == 1

        entry2 = store.get_or_create_session(source)
        assert entry2.was_auto_reset is False
        assert entry2.session_id == original_session_id
        assert entry2.resume_notice_reason == SUSPEND_REASON_INTERRUPTED_RESTART
        assert entry2.suspended is False
        assert entry2.suspend_reason is None

    def test_manual_stop_still_auto_resets_with_reason(self, tmp_path):
        store = _make_store(
            SessionResetPolicy(mode="none"),
            tmp_path,
        )
        source = _make_source()

        entry1 = store.get_or_create_session(source)
        assert store.suspend_session(
            entry1.session_key,
            reason=SUSPEND_REASON_MANUAL_STOP,
        )

        entry2 = store.get_or_create_session(source)
        assert entry2.was_auto_reset is True
        assert entry2.auto_reset_reason == SUSPEND_REASON_MANUAL_STOP
        assert entry2.session_id != entry1.session_id

    def test_legacy_suspended_entry_migrates_to_resume_notice(self, tmp_path):
        source = _make_source()
        sessions_file = tmp_path / "sessions.json"
        now = datetime.now().isoformat()
        legacy_entry = {
            "session_key": "agent:main:telegram:dm:123",
            "session_id": "legacy_session",
            "created_at": now,
            "updated_at": now,
            "display_name": None,
            "platform": "telegram",
            "chat_type": "dm",
            "input_tokens": 0,
            "output_tokens": 0,
            "cache_read_tokens": 0,
            "cache_write_tokens": 0,
            "total_tokens": 0,
            "last_prompt_tokens": 0,
            "estimated_cost_usd": 0.0,
            "cost_status": "unknown",
            "memory_flushed": False,
            "suspended": True,
        }
        sessions_file.write_text(
            json.dumps({legacy_entry["session_key"]: legacy_entry}),
            encoding="utf-8",
        )

        store = _make_store(
            SessionResetPolicy(mode="none"),
            tmp_path,
        )
        entry = store.get_or_create_session(source)

        assert entry.session_id == "legacy_session"
        assert entry.was_auto_reset is False
        assert entry.resume_notice_reason == SUSPEND_REASON_INTERRUPTED_RESTART
        assert entry.suspended is False


# ---------------------------------------------------------------------------
# SessionResetPolicy notify config
# ---------------------------------------------------------------------------

class TestResetPolicyNotify:
    def test_notify_defaults_true(self):
        policy = SessionResetPolicy()
        assert policy.notify is True

    def test_notify_exclude_defaults(self):
        policy = SessionResetPolicy()
        assert "api_server" in policy.notify_exclude_platforms
        assert "webhook" in policy.notify_exclude_platforms

    def test_from_dict_with_notify_false(self):
        policy = SessionResetPolicy.from_dict({"notify": False})
        assert policy.notify is False

    def test_from_dict_with_custom_excludes(self):
        policy = SessionResetPolicy.from_dict({
            "notify_exclude_platforms": ["api_server", "webhook", "homeassistant"],
        })
        assert "homeassistant" in policy.notify_exclude_platforms

    def test_from_dict_preserves_defaults_on_missing_keys(self):
        policy = SessionResetPolicy.from_dict({})
        assert policy.notify is True
        assert "api_server" in policy.notify_exclude_platforms

    def test_to_dict_roundtrip(self):
        original = SessionResetPolicy(
            mode="idle",
            notify=False,
            notify_exclude_platforms=("api_server",),
        )
        restored = SessionResetPolicy.from_dict(original.to_dict())
        assert restored.notify == original.notify
        assert restored.notify_exclude_platforms == original.notify_exclude_platforms
        assert restored.mode == original.mode
