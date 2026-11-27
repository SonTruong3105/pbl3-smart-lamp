from collections import deque

import numpy as np

from app.core.providers.vad.silero import SileroVAD


def _vad_stub(probabilities):
    vad = SileroVAD.__new__(SileroVAD)
    vad.sample_rate = 16000
    vad.threshold = 0.6
    vad.threshold_low = 0.2
    vad.silence_duration_ms = 64
    vad.min_speech_duration_ms = 32
    vad.frame_duration_ms = 32
    vad.max_samples = 16000 * 30
    vad.pre_speech_samples = 512
    vad.post_speech_samples = 0
    vad.pcm_buffer = deque()
    vad.pcm_buffer_len = 0
    vad.audio_buffer = deque(maxlen=vad.max_samples)
    vad.pre_buffer = deque(maxlen=vad.pre_speech_samples)
    vad.is_in_speech = False
    vad.speech_frames = 0
    vad.silence_frames = 0
    vad.total_frames = 0
    vad._state = None
    vad._context = None
    probs = iter(probabilities)
    vad._infer = lambda _frame: next(probs)
    return vad


def test_triggering_frame_is_not_duplicated():
    vad = _vad_stub([0.0, 0.9, 0.9, 0.0, 0.0])
    frames = [np.full(512, i, dtype=np.int16) for i in range(1, 6)]
    ended = False
    for frame in frames:
        ended = vad.push(frame.tobytes())
    audio = np.frombuffer(vad.get_audio(), dtype=np.int16)
    assert ended
    assert len(audio) == 5 * 512
    assert np.count_nonzero(audio == 2) == 512


def test_reset_clears_partial_frames_and_speech_state():
    vad = _vad_stub([0.9])
    vad.push(np.ones(512, dtype=np.int16).tobytes())
    assert vad.has_speech()
    vad.reset()
    assert not vad.has_speech()
    assert vad.get_audio() == b""
    assert vad.pcm_buffer_len == 0
