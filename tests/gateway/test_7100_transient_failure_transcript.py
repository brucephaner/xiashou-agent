"""Tests for #7100 transient failures preserving the user transcript turn."""


def _classify(agent_result: dict, history_len: int) -> tuple[bool, bool]:
    agent_failed_early = bool(agent_result.get("failed"))
    err = str(agent_result.get("error", "")).lower()
    is_context_overflow_failure = agent_failed_early and (
        bool(agent_result.get("compression_exhausted"))
        or any(p in err for p in (
            "context length", "context size", "context window",
            "maximum context", "token limit", "too many tokens",
            "reduce the length", "exceeds the limit",
            "request entity too large", "prompt is too long",
            "payload too large", "input is too long",
        ))
        or ("400" in err and history_len > 50)
    )
    return agent_failed_early, is_context_overflow_failure


class TestContextOverflowStillSkipsTranscript:
    def test_compression_exhausted_is_context_overflow(self):
        failed, ctx_overflow = _classify(
            {
                "failed": True,
                "compression_exhausted": True,
                "error": "Request payload too large: max compression attempts reached.",
            },
            history_len=100,
        )

        assert failed
        assert ctx_overflow

    def test_explicit_context_length_error_is_context_overflow(self):
        failed, ctx_overflow = _classify(
            {"failed": True, "error": "prompt is too long: 250000 tokens"},
            history_len=10,
        )

        assert failed
        assert ctx_overflow

    def test_generic_400_on_large_session_is_context_overflow(self):
        failed, ctx_overflow = _classify(
            {"failed": True, "error": "error code: 400 - {'message': 'Error'}"},
            history_len=100,
        )

        assert failed
        assert ctx_overflow


class TestTransientFailureKeepsUserMessage:
    def test_rate_limit_429_is_not_context_overflow(self):
        failed, ctx_overflow = _classify(
            {
                "failed": True,
                "error": "429 Too Many Requests - rate limit exceeded",
            },
            history_len=10,
        )

        assert failed
        assert not ctx_overflow

    def test_read_timeout_is_not_context_overflow(self):
        failed, ctx_overflow = _classify(
            {"failed": True, "error": "ReadTimeout: Read timed out."},
            history_len=10,
        )

        assert failed
        assert not ctx_overflow

    def test_connection_reset_is_not_context_overflow(self):
        failed, ctx_overflow = _classify(
            {"failed": True, "error": "Connection reset by peer"},
            history_len=10,
        )

        assert failed
        assert not ctx_overflow

    def test_provider_500_is_not_context_overflow(self):
        failed, ctx_overflow = _classify(
            {"failed": True, "error": "500 Internal Server Error"},
            history_len=10,
        )

        assert failed
        assert not ctx_overflow

    def test_generic_400_on_short_session_is_not_context_overflow(self):
        failed, ctx_overflow = _classify(
            {"failed": True, "error": "error code: 400 - invalid model"},
            history_len=5,
        )

        assert failed
        assert not ctx_overflow


class TestSuccessfulResultUnaffected:
    def test_successful_result_neither_failed_nor_overflow(self):
        failed, ctx_overflow = _classify(
            {"final_response": "Hello!", "messages": [{"role": "assistant"}]},
            history_len=10,
        )

        assert not failed
        assert not ctx_overflow
