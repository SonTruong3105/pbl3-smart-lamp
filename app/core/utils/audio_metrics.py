"""Small privacy-safe PCM metrics for diagnosing speech capture quality."""
from __future__ import annotations

from array import array
import math
import sys


def summarize_pcm16_mono(pcm: bytes, sample_rate: int = 16000) -> dict:
    """Return duration/level metrics without retaining or logging audio content."""
    if not pcm or sample_rate <= 0:
        return {"duration_ms": 0, "peak_dbfs": None, "rms_dbfs": None, "clipping_pct": 0.0}

    usable = len(pcm) - (len(pcm) % 2)
    samples = array("h")
    samples.frombytes(pcm[:usable])
    if sys.byteorder != "little":
        samples.byteswap()
    count = len(samples)
    if not count:
        return {"duration_ms": 0, "peak_dbfs": None, "rms_dbfs": None, "clipping_pct": 0.0}

    peak = max(abs(value) for value in samples) / 32768.0
    mean_square = sum(value * value for value in samples) / (count * 32768.0 * 32768.0)
    rms = math.sqrt(mean_square)
    clipped = sum(1 for value in samples if abs(value) >= 32760)

    def dbfs(amplitude: float) -> float:
        return round(20.0 * math.log10(max(amplitude, 1e-8)), 1)

    return {
        "duration_ms": round(count * 1000.0 / sample_rate),
        "peak_dbfs": dbfs(peak),
        "rms_dbfs": dbfs(rms),
        "clipping_pct": round(clipped * 100.0 / count, 3),
    }
