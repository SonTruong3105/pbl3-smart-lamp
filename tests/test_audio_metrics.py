import array
import sys

from app.core.utils.audio_metrics import summarize_pcm16_mono


def test_pcm_metrics_report_duration_levels_and_clipping_without_audio():
    samples = array.array("h", [0, 1000, -1000, 32767])
    if sys.byteorder != "little":
        samples.byteswap()
    metrics = summarize_pcm16_mono(samples.tobytes(), sample_rate=16000)
    assert metrics["duration_ms"] == 0  # Four samples are less than one millisecond.
    assert metrics["peak_dbfs"] == 0.0
    assert metrics["rms_dbfs"] is not None
    assert metrics["clipping_pct"] == 25.0
    assert "audio" not in metrics


def test_empty_pcm_metrics_are_safe():
    assert summarize_pcm16_mono(b"") == {
        "duration_ms": 0,
        "peak_dbfs": None,
        "rms_dbfs": None,
        "clipping_pct": 0.0,
    }
