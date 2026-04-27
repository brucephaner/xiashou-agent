"""Default SOUL.md content seeded into HERMES_HOME on first run.

Single source of truth for the agent's default identity. This same string
is used as both the file seed (`_ensure_default_soul_md`) and the runtime
fallback (`DEFAULT_AGENT_IDENTITY` in `agent.prompt_builder`) when no
SOUL.md exists on disk.

The host app (daoling desktop shell) injects brand/version separately via
the `HOST_IDENTITY_META` slot, so this string deliberately omits version
interpolation — it stays stable across releases and the migration check
below can compare by exact bytes.
"""

DEFAULT_SOUL_MD = (
    "你是叨灵，运行在用户电脑上，仅通过微信跟用户沟通。"
    "回复像真人聊天，简短自然，不确定就直说，不瞎编。"
    "你能上网、看图、读写文件、写代码跑代码。\n"
)


# Past Rust `MANAGED_SOUL_MD` constants, oldest → newest. When
# `_ensure_default_soul_md` finds the user's file matches one of these
# byte-for-byte, we treat it as unmodified default and overwrite with
# the current `DEFAULT_SOUL_MD`. Anything else is presumed
# user-customized and left alone.
LEGACY_DEFAULT_SOUL_MDS: tuple[str, ...] = (
    "你是叨灵，通过微信跟用户沟通。回复像正常人聊天，短一点，不确定就直说。\n",
    "你是叨灵，通过微信跟用户沟通。回复像真人聊天，简短自然，不确定就直说。\n",
    "你是叨灵，通过微信跟用户沟通。回复像真人聊天，简短自然，不确定就直说，不瞎编。\n",
    "你是叨灵，跑在用户电脑上，通过微信跟用户沟通。回复像真人聊天，简短自然，不确定就直说，不瞎编。\n",
    "你是叨灵，运行在用户电脑上，通过微信跟用户沟通。回复像真人聊天，简短自然，不确定就直说，不瞎编。\n",
    "你是叨灵，运行在用户电脑上，仅通过微信跟用户沟通。回复像真人聊天，简短自然，不确定就直说，不瞎编。\n",
)


# Substring fingerprint of the previous English fallback template (which
# interpolated brand/version, so exact-match doesn't work). If the file
# starts with "You are " and contains this phrase, it's a stale framework
# default from before the persona consolidation.
_LEGACY_ENGLISH_FINGERPRINT = (
    "an intelligent AI assistant. You are helpful, knowledgeable, and direct"
)


def is_stale_default_soul_md(content: str) -> bool:
    """True if `content` matches a known stale default we should overwrite."""
    if content in LEGACY_DEFAULT_SOUL_MDS:
        return True
    return content.startswith("You are ") and _LEGACY_ENGLISH_FINGERPRINT in content
