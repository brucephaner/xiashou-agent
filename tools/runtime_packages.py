"""Background sync of runtime Python packages from tools/manifest/.

The gateway fires `sync_runtime_packages_async()` on startup. A daemon thread
diffs the manifest against the interpreter's site-packages, pip-installs what's
missing from a domestic mirror, and writes the outcome to the gateway log.

Fully silent to the end user — no UI, no chat messages, no approval prompts.
Failures degrade gracefully: the agent falls back to today's dynamic install
flow if a package is still missing when a task needs it.
"""

from __future__ import annotations

import importlib.util
import logging
import os
import platform
import subprocess
import sys
import threading
from pathlib import Path
from typing import Callable, Iterable

logger = logging.getLogger(__name__)

_MIRROR = os.environ.get(
    "XIASHOU_PIP_MIRROR",
    "https://pypi.tuna.tsinghua.edu.cn/simple",
)
_INSTALL_TIMEOUT_SEC = 600

# pip install name → top-level import name, only where the two differ.
# PyMuPDF is always importable as `fitz` (every version, including 1.24+ which
# also exposes `pymupdf`); checking `fitz` avoids reinstalling when an older
# version is already present.
_IMPORT_NAMES: dict[str, str] = {
    "beautifulsoup4": "bs4",
    "python-docx": "docx",
    "python-pptx": "pptx",
    "Pillow": "PIL",
    "pymupdf": "fitz",
    "youtube-transcript-api": "youtube_transcript_api",
}


def _manifest_dir() -> Path:
    return Path(__file__).parent / "manifest"


def _read_manifest(name: str) -> list[str]:
    path = _manifest_dir() / f"{name}.txt"
    if not path.exists():
        return []
    pkgs: list[str] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        pkgs.append(line)
    return pkgs


def _target_packages() -> list[str]:
    pkgs = _read_manifest("common")
    sysname = platform.system().lower()
    if sysname == "windows":
        pkgs.extend(_read_manifest("windows"))
    elif sysname == "darwin":
        pkgs.extend(_read_manifest("macos"))
    # Dedupe preserving order, case-insensitive.
    seen: set[str] = set()
    out: list[str] = []
    for p in pkgs:
        key = p.lower()
        if key not in seen:
            seen.add(key)
            out.append(p)
    return out


def _import_name_for(pkg: str) -> str:
    return _IMPORT_NAMES.get(pkg, pkg.replace("-", "_"))


def _is_installed(pkg: str) -> bool:
    name = _import_name_for(pkg)
    try:
        return importlib.util.find_spec(name) is not None
    except (ValueError, ImportError, ModuleNotFoundError):
        return False


# Post-install warmup hooks: pip install name → callable run once after a
# successful install. Use sparingly — only for packages whose first real use
# triggers a significant network/model download that'd otherwise block the
# user. Runs inside sync_runtime_packages_async()'s daemon thread.
_WARMUPS: dict[str, Callable[[], None]] = {}


def _warmup_rapidocr() -> None:
    """Instantiate RapidOCR once to trigger PP-OCRv5 model download (~150 MB)
    from ModelScope CDN. Without this, the user's first OCR call in WeChat
    would block 30–60s on the download."""
    try:
        from rapidocr_onnxruntime import RapidOCR
        RapidOCR()
        logger.info("runtime-packages: rapidocr models warmed up")
    except Exception as exc:
        logger.warning("runtime-packages: rapidocr warmup failed: %s", exc)


_WARMUPS["rapidocr-onnxruntime"] = _warmup_rapidocr


def _pip_install(pkgs: Iterable[str]) -> int:
    pkg_list = list(pkgs)
    if not pkg_list:
        return 0
    cmd = [
        sys.executable,
        "-m",
        "pip",
        "install",
        "--disable-pip-version-check",
        "--no-input",
        "-i",
        _MIRROR,
        *pkg_list,
    ]
    logger.info(
        "runtime-packages: installing %d package(s) from %s: %s",
        len(pkg_list),
        _MIRROR,
        " ".join(pkg_list),
    )
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=_INSTALL_TIMEOUT_SEC,
        )
    except subprocess.TimeoutExpired:
        logger.warning(
            "runtime-packages: pip install timed out after %ds", _INSTALL_TIMEOUT_SEC
        )
        return -1
    except Exception as exc:
        logger.warning("runtime-packages: pip install exception: %s", exc)
        return -1

    if result.returncode != 0:
        tail = (result.stderr or result.stdout or "").strip().splitlines()[-10:]
        logger.warning(
            "runtime-packages: pip exited %d\n%s",
            result.returncode,
            "\n".join(tail),
        )
    else:
        logger.info(
            "runtime-packages: installed %d package(s) successfully", len(pkg_list)
        )
    return result.returncode


def sync_runtime_packages() -> None:
    """Blocking diff-and-install. Use the async wrapper from gateway startup."""
    try:
        wanted = _target_packages()
    except Exception as exc:
        logger.warning("runtime-packages: failed to read manifest: %s", exc)
        return

    if not wanted:
        return

    try:
        missing = [p for p in wanted if not _is_installed(p)]
    except Exception as exc:
        logger.warning("runtime-packages: presence check failed: %s", exc)
        return

    if not missing:
        logger.debug(
            "runtime-packages: all %d manifest package(s) already present", len(wanted)
        )
        return

    rc = _pip_install(missing)
    if rc == 0:
        for pkg in missing:
            fn = _WARMUPS.get(pkg.lower())
            if fn is not None:
                fn()


def sync_runtime_packages_async() -> threading.Thread:
    """Fire-and-forget daemon thread. Never blocks gateway startup."""
    thread = threading.Thread(
        target=sync_runtime_packages,
        name="runtime-packages-sync",
        daemon=True,
    )
    thread.start()
    return thread
