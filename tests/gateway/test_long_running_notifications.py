"""Tests for localized long-running gateway notifications."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from gateway.run import _format_long_running_status_message


def test_formats_long_running_message_with_current_tool():
    message = _format_long_running_status_message(
        10,
        {
            "api_call_count": 1,
            "max_iterations": 90,
            "current_tool": "terminal",
            "last_activity_desc": "executing tool: terminal",
        },
    )

    assert message == "⏳ 还在处理中...（已耗时 10 分钟，第 1/90 次迭代，正在运行：terminal）"


def test_formats_long_running_message_with_last_activity_fallback():
    message = _format_long_running_status_message(
        3,
        {
            "api_call_count": 5,
            "max_iterations": 90,
            "current_tool": None,
            "last_activity_desc": "等待模型响应",
        },
    )

    assert message == "⏳ 还在处理中...（已耗时 3 分钟，第 5/90 次迭代，等待模型响应）"


def test_formats_long_running_message_without_activity():
    assert _format_long_running_status_message(10) == "⏳ 还在处理中...（已耗时 10 分钟）"
