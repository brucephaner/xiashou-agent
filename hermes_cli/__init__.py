"""
Hermes CLI - Unified command-line interface for Hermes Agent.

Provides subcommands for:
- hermes chat          - Interactive chat (same as ./hermes)
- hermes gateway       - Run gateway in foreground
- hermes gateway start - Start gateway service
- hermes gateway stop  - Stop gateway service
- hermes setup         - Interactive setup wizard
- hermes status        - Show status of all components
- hermes cron          - Manage cron jobs
"""

import os

__version__ = "0.9.0"
__release_date__ = "2026.4.13"


def get_brand() -> str:
    """User-facing product name.

    Host apps that embed this agent (e.g. a desktop shell) override the
    display brand by setting `DAOLING_BRAND`. Unset → neutral default
    so the bare framework keeps working standalone without leaking a
    host-specific brand name.
    """
    return os.environ.get("DAOLING_BRAND") or "AI Assistant"


def get_display_version() -> str:
    """User-facing version string.

    Host apps override via `DAOLING_VERSION` so the agent reports the
    host app's version (e.g. the desktop shell's semver) rather than
    the bundled agent framework's internal `__version__`. The two are
    intentionally decoupled: `__version__` stays as an internal API
    version identifier, `get_display_version()` is what users see.
    """
    return os.environ.get("DAOLING_VERSION") or __version__
