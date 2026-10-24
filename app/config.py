"""Config loader với lazy loading — hỗ trợ selected_module pattern."""
import os
import re
import yaml
from pathlib import Path

# Load .env nếu có
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

_ENV_VAR_RE = re.compile(r'\$\{([A-Za-z_][A-Za-z0-9_]*)\}')


def _expand_env(value):
    if isinstance(value, str):
        def _repl(m):
            return os.environ.get(m.group(1), m.group(0))
        return _ENV_VAR_RE.sub(_repl, value)
    if isinstance(value, dict):
        return {k: _expand_env(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_expand_env(v) for v in value]
    return value


class Config:
    def __init__(self, path: str = "config.yaml"):
        with open(path, "r", encoding="utf-8") as f:
            raw = yaml.safe_load(f)
        self._data = _expand_env(raw)

    def _get(self, *keys, default=None):
        node = self._data
        for k in keys:
            if not isinstance(node, dict) or k not in node:
                return default
            node = node[k]
        return node

    def _selected(self, module: str) -> dict:
        """Trả về config dict của module được chọn."""
        # Hỗ trợ cả selected_module (mới) và flat (cũ)
        name = self._get("selected_module", module)
        if name:
            cfg = self._get(module, name, default={})
            if cfg:
                return cfg
        # Fallback: đọc flat key (vd: llm:, asr:)
        flat_name = module.lower()
        return self._get(flat_name, default={}) or {}

    # === SERVER ===
    @property
    def version(self) -> str:
        return self._get("server", "version", default="2.0.0")

    @property
    def host(self) -> str:
        return self._get("server", "host", default="0.0.0.0")

    @property
    def port(self) -> int:
        return self._get("server", "port", default=8000)

    @property
    def auth_enabled(self) -> bool:
        return self._get("server", "auth", "enabled", default=False)

    # === SELECTED MODULES ===
    @property
    def vad_provider(self) -> str:
        return self._get("selected_module", "VAD", default="energy")

    @property
    def asr_provider(self) -> str:
        return self._get("selected_module", "ASR", default="phowhisper")

    @property
    def llm_provider(self) -> str:
        return self._get("selected_module", "LLM", default="ollama")

    @property
    def tts_provider(self) -> str:
        return self._get("selected_module", "TTS", default="edge")

    @property
    def memory_provider(self) -> str:
        return self._get("selected_module", "Memory", default="local")

    @property
    def intent_provider(self) -> str:
        return self._get("selected_module", "Intent", default="function_call")

    # === VAD ===
    @property
    def vad_config(self) -> dict:
        return self._selected("VAD")

    @property
    def vad_silence_ms(self) -> int:
        return self.vad_config.get("silence_duration_ms",
                self.vad_config.get("min_silence_duration_ms", 700))

    @property
    def vad_min_speech_ms(self) -> int:
        return self.vad_config.get("min_speech_duration_ms", 300)

    @property
    def vad_energy_margin_db(self) -> float:
        return self.vad_config.get("energy_margin_db", 6.0)

    @property
    def vad_hangover_ms(self) -> int:
        return self.vad_config.get("hangover_ms", 200)

    @property
    def vad_pre_speech_ms(self) -> int:
        return self.vad_config.get("pre_speech_ms", 200)

    @property
    def vad_post_speech_ms(self) -> int:
        return self.vad_config.get("post_speech_ms", 300)

    @property
    def vad_threshold(self) -> float:
        return self.vad_config.get("threshold", 0.5)

    @property
    def vad_threshold_low(self) -> float:
        return self.vad_config.get("threshold_low", 0.2)

    @property
    def vad_frame_window_threshold(self) -> int:
        return self.vad_config.get("frame_window_threshold", 3)

    @property
    def vad_model_dir(self) -> str:
        return self.vad_config.get("model_dir", "models/snakers4_silero-vad")

    @property
    def vad_initial_threshold(self) -> float:
        return self.vad_config.get("initial_threshold", 500.0)

    # === LLM ===
    @property
    def llm_config(self) -> dict:
        return self._selected("LLM")

    @property
    def llm_url(self) -> str:
        return self.llm_config.get("url", "http://localhost:11434/api/chat")

    @property
    def llm_model(self) -> str:
        return self.llm_config.get("model", "qwen3.5:4b")

    @property
    def llm_temperature(self) -> float:
        return self.llm_config.get("temperature", 0.7)

    @property
    def llm_num_predict(self) -> int:
        return self.llm_config.get("num_predict", 512)

    @property
    def llm_max_tool_iterations(self) -> int:
        return self.llm_config.get("max_tool_iterations", 5)

    @property
    def llm_request_timeout(self) -> float:
        return self.llm_config.get("request_timeout", 120.0)

    @property
    def llm_token_timeout(self) -> float:
        return self.llm_config.get("token_timeout", 60.0)

    @property
    def llm_history_keep(self) -> int:
        return self.llm_config.get("history_keep", 20)

    @property
    def llm_think(self) -> bool:
        # ✅ Qwen 3.5 có thinking — tắt mặc định
        return self.llm_config.get("think", False)

    @property
    def llm_num_ctx(self):
        return self.llm_config.get("num_ctx")

    @property
    def llm_num_batch(self):
        return self.llm_config.get("num_batch")

    @property
    def llm_keep_alive(self):
        return self.llm_config.get("keep_alive")

    @property
    def system_prompt(self) -> str:
        return self.llm_config.get("system_prompt", "")

    # === ASR ===
    @property
    def asr_config(self) -> dict:
        return self._selected("ASR")

    @property
    def asr_url(self) -> str:
        return self.asr_config.get("url")

    @property
    def asr_model(self) -> str:
        return self.asr_config.get("model", "phowhisper")

    @property
    def asr_language(self) -> str:
        return self.asr_config.get("language", "vi")

    @property
    def asr_request_timeout(self) -> float:
        return self.asr_config.get("request_timeout", 60.0)

    @property
    def asr_output_dir(self) -> str:
        return self.asr_config.get("output_dir", "tmp/")

    # === TTS ===
    @property
    def tts_config(self) -> dict:
        return self._selected("TTS")

    @property
    def tts_interface_type(self) -> str:
        return self.tts_config.get("interface_type", "non_stream")

    @property
    def tts_voice(self) -> str:
        return self.tts_config.get("voice", "vi-VN-HoaiMyNeural")

    @property
    def tts_rate(self) -> str:
        return self.tts_config.get("rate", "+0%")

    @property
    def tts_volume(self) -> str:
        return self.tts_config.get("volume", "+0%")

    @property
    def tts_request_timeout(self) -> float:
        return self.tts_config.get("request_timeout", 30.0)

    @property
    def tts_max_retries(self) -> int:
        return self.tts_config.get("max_retries", 3)

    @property
    def tts_vieneu_url(self) -> str:
        return self.tts_config.get("url", "http://localhost:11436")

    @property
    def tts_edge_voice(self) -> str:
        return self.tts_config.get("voice", "vi-VN-HoaiMyNeural")

    @property
    def tts_piper_model(self) -> str:
        return self.tts_config.get("model",
            "models/piper/vi_VN-vais1000-medium.onnx")

    @property
    def tts_piper_binary(self) -> str:
        return self.tts_config.get("binary", "python")

    # === MEMORY ===
    @property
    def memory_config(self) -> dict:
        return self._selected("Memory")

    @property
    def memory_max_turns(self) -> int:
        return self.memory_config.get("max_turns", 20)

    # === AUDIO ===
    @property
    def sample_rate(self) -> int:
        return self._get("audio", "sample_rate", default=16000)

    @property
    def channels(self) -> int:
        return self._get("audio", "channels", default=1)

    @property
    def frame_duration(self) -> int:
        return self._get("audio", "frame_duration", default=60)

    @property
    def pre_buffer_count(self) -> int:
        return self._get("audio", "pre_buffer_count", default=3)

    @property
    def server_sample_rate(self) -> int:
        return self._get("audio", "server_sample_rate", default=24000)

    # === PIPELINE ===
    @property
    def min_sentence_len(self) -> int:
        return self._get("pipeline", "min_sentence_len", default=8)

    @property
    def max_buffer_len(self) -> int:
        return self._get("pipeline", "max_buffer_len", default=100)

    @property
    def tts_workers(self) -> int:
        return self._get("pipeline", "tts_workers", default=1)

    # === SEARCH ===
    @property
    def searxng_url(self) -> str:
        return self._get("search", "searxng_url",
                         default="http://localhost:8888/search")

    @property
    def searxng_timeout(self) -> float:
        return self._get("search", "searxng_timeout", default=15.0)

    @property
    def weather_timeout(self) -> float:
        return self._get("search", "weather_timeout", default=8.0)

    @property
    def search_max_results(self) -> int:
        return self._get("search", "max_results", default=5)

    # === TAVILY ===
    @property
    def tavily_api_key(self) -> str:
        return self._get("search", "tavily_api_key", default="")

    # === WIKIPEDIA ===
    @property
    def wiki_lang(self) -> str:
        return self._get("search", "wiki_lang", default="vi")

    # === INTENT ===
    @property
    def intent_url(self) -> str:
        return self._get("intent", "url",
                         default="http://localhost:11434/api/chat")

    @property
    def intent_model(self) -> str:
        return self._get("intent", "model", default="qwen2.5:1.5b")

    @property
    def intent_timeout(self) -> float:
        return self._get("intent", "timeout", default=5.0)

    # === TUNNEL ===
    @property
    def ngrok_ota_url(self) -> str:
        return self._get("tunnel", "ngrok_url", default="")

    @property
    def cloudflare_ws_url(self) -> str:
        return self._get("tunnel", "ws_url", default="")

    # === SESSION ===
    @property
    def session_resume_window_minutes(self) -> int:
        return self._get("session", "resume_window_minutes", default=30)

    @property
    def session_cleanup_days(self) -> int:
        return self._get("session", "cleanup_days", default=7)

    @property
    def session_max_idle_duration(self) -> int:
        return self._get("session", "max_idle_duration", default=300)

    # === LOGGING ===
    @property
    def log_level(self) -> str:
        return self._get("logging", "level", default="INFO")

    @property
    def log_dir(self) -> str:
        return self._get("logging", "log_dir", default="logs")

    @property
    def log_retention_days(self) -> int:
        return self._get("logging", "retention_days", default=7)

    @property
    def log_main_rotation_mb(self) -> int:
        return self._get("logging", "main_rotation_mb", default=10)

    @property
    def log_error_rotation_mb(self) -> int:
        return self._get("logging", "error_rotation_mb", default=5)

    # === DATABASE ===
    @property
    def db_path(self) -> str:
        return self._get("database", "path", default="data/xiaozhi.db")


    # === MQTT ===
    @property
    def mqtt_enabled(self) -> bool:
        return self._get("mqtt", "enabled", default=False)

    @property
    def mqtt_broker_host(self) -> str:
        return self._get("mqtt", "broker_host", default="localhost")

    @property
    def mqtt_broker_port(self) -> int:
        return self._get("mqtt", "broker_port", default=1883)

    @property
    def mqtt_username(self) -> str:
        return self._get("mqtt", "username", default="")

    @property
    def mqtt_password(self) -> str:
        return self._get("mqtt", "password", default="")

    @property
    def mqtt_endpoint(self) -> str:
        return self._get("mqtt", "endpoint", default="192.168.1.19")

    # === UDP ===
    @property
    def udp_host(self) -> str:
        return self._get("udp", "host", default="0.0.0.0")

    @property
    def udp_port(self) -> int:
        return self._get("udp", "port", default=8884)

    @property
    def udp_endpoint(self) -> str:
        return self._get("udp", "endpoint", default="192.168.1.19")
_config = None


def get_config() -> Config:
    global _config
    if _config is None:
        _config = Config()
    return _config


class _ConfigProxy:
    def __getattr__(self, name):
        return getattr(get_config(), name)


config = _ConfigProxy()