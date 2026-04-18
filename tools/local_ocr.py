"""Local OCR fallback via RapidOCR (PP-OCRv5).

Used when cloud vision is unavailable — non-multimodal main model + no
auxiliary.vision configured, or cloud call failed. Best-effort: ImportError
or init failure returns None, caller decides fallback behavior.

rapidocr-onnxruntime is installed via tools/manifest/common.txt and pre-warmed
by tools/runtime_packages.py so the first OCR call is already model-loaded.
"""

from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

_ENGINE = None
_ENGINE_LOCK = threading.Lock()


def _get_engine():
    global _ENGINE
    if _ENGINE is not None:
        return _ENGINE
    with _ENGINE_LOCK:
        if _ENGINE is not None:
            return _ENGINE
        try:
            from rapidocr_onnxruntime import RapidOCR
        except ImportError:
            logger.debug("local_ocr: rapidocr-onnxruntime not installed")
            return None
        try:
            _ENGINE = RapidOCR()
        except Exception as exc:
            logger.warning("local_ocr: RapidOCR init failed: %s", exc)
            return None
    return _ENGINE


def extract_text(image_path: str | Path) -> Optional[str]:
    """Return newline-joined OCR text, or None if unavailable/failed."""
    engine = _get_engine()
    if engine is None:
        return None
    try:
        result, _ = engine(str(image_path))
    except Exception as exc:
        logger.warning("local_ocr: OCR call failed: %s", exc)
        return None
    if not result:
        return ""
    lines = [r[1] for r in result if len(r) >= 2 and r[1]]
    return "\n".join(lines)
