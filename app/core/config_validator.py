"""Startup config validator — fail-fast thay vì crash giữa chừng.

Học từ AI Chatbot (create_app validation).
"""
from __future__ import annotations

import os
from pathlib import Path

from loguru import logger

__all__ = ["validate", "validate_or_warn"]


def validate() -> list[str]:
    """Trả về danh sách warning (rỗng = OK)."""
    warnings: list[str] = []

    try:
        from app.config import config
    except Exception as e:
        return [f"Không load được config: {e}"]

    # ─── Server ──────────────────────────────────────────────────
    if not (1 <= config.port <= 65535):
        warnings.append(f"server.port={config.port} ngoài khoảng 1-65535")

    # ─── Auth ────────────────────────────────────────────────────
    if config.auth_enabled:
        devices_file = Path("data/devices.json")
        if not devices_file.exists():
            warnings.append(
                f"auth.enabled=true nhưng {devices_file} không tồn tại — "
                f"mọi ESP32 sẽ bị từ chối"
            )

    # ─── LLM ─────────────────────────────────────────────────────
    if not config.llm_url:
        warnings.append("LLM url rỗng")
    if not config.llm_model:
        warnings.append("LLM model rỗng")

    # ─── TTS ─────────────────────────────────────────────────────
    provider = config.tts_provider
    if provider == "vieneu" and not config.tts_vieneu_url:
        warnings.append("TTS provider='vieneu' nhưng url rỗng")
    if provider == "piper":
        model = config.tts_piper_model
        if model and not Path(model).exists():
            warnings.append(f"Piper model không tồn tại: {model}")

    # ─── VAD ─────────────────────────────────────────────────────
    if config.vad_provider == "silero":
        md = config.vad_model_dir
        expected = Path(md) / "silero_vad.onnx"
        if not expected.exists():
            warnings.append(f"Silero VAD model không tồn tại: {expected}")

    # ─── Database ────────────────────────────────────────────────
    db_dir = Path(config.db_path).parent
    if not db_dir.exists():
        try:
            if not os.access(db_dir.parent, os.W_OK):
                warnings.append(f"Không có quyền ghi vào {db_dir.parent}")
        except Exception:
            pass

    # ─── Intent ──────────────────────────────────────────────────
    if config.intent_provider == "intent_llm":
        if not config.intent_url:
            warnings.append("intent.provider='intent_llm' nhưng url rỗng")

    return warnings


def validate_or_warn() -> int:
    """Chạy validate, log warning, trả về số warning."""
    warnings = validate()
    if not warnings:
        logger.info("✅ Config hợp lệ")
        return 0

    logger.warning(f"⚠️ Config có {len(warnings)} vấn đề tiềm ẩn:")
    for w in warnings:
        logger.warning(f"   • {w}")
    return len(warnings)


if __name__ == "__main__":
    validate_or_warn()