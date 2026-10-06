"""Vagar configuration: paths, user profile, and service settings.

All machine-specific paths resolve from VAGAR_HOME (the directory containing
this file), so a fresh clone works without editing code. Personalize by copying
.env.example to .env and filling in your values, or by setting environment
variables directly.

No secrets are stored here. API keys and tokens belong in .env (git-ignored).
"""
import os
from pathlib import Path

# --- project root: every path below derives from this ---
VAGAR_HOME = Path(__file__).resolve().parent


def _env(name: str, default: str = "") -> str:
    """Read an env var, falling back to default when unset or empty."""
    val = os.environ.get(name)
    return val if val not in (None, "") else default


# --- user profile (personalize in .env; never commit personal details) ---
USER_NAME = _env("VAGAR_USER_NAME", "friend")
USER_FORMAL_NAME = _env("VAGAR_USER_FORMAL_NAME", "sir")
USER_BIO = _env(
    "VAGAR_USER_BIO",
    "They built you. They prefer clear, plain language and direct answers.",
)
ASSISTANT_NAME = _env("VAGAR_NAME", "Vagar")

# --- data directory (runtime JSON/MD files live here) ---
DATA_DIR = Path(_env("VAGAR_DATA_DIR", str(VAGAR_HOME)))

# --- data files ---
IDENTITY_PATH = DATA_DIR / "identity.json"
MEMORY_PATH = DATA_DIR / "vagar_memory.md"
QUESTS_PATH = DATA_DIR / "quests.json"
REMINDERS_PATH = DATA_DIR / "reminders.json"
STANDING_REMINDERS_PATH = DATA_DIR / "standing_reminders.json"
LAST_SESSION_PATH = DATA_DIR / "last_session.json"
LAST_BRIEFING_PATH = DATA_DIR / "last_briefing.txt"
HEARTBEAT_PATH = DATA_DIR / "heartbeat.txt"
MUTE_STATE_PATH = DATA_DIR / ".mute_state"
LAST_FRAME_PATH = DATA_DIR / "last_frame.jpg"

# --- skills ---
SKILLS_DIR = VAGAR_HOME / "skills"

# --- voice (Kokoro TTS, local ONNX) ---
KOKORO_MODEL_PATH = Path(
    _env("VAGAR_KOKORO_MODEL", str(VAGAR_HOME / "voices" / "kokoro" / "model_q4.onnx"))
)
KOKORO_VOICES_PATH = Path(
    _env("VAGAR_KOKORO_VOICES", str(VAGAR_HOME / "voices" / "kokoro" / "voices.npz"))
)
KOKORO_VOICE = _env("VAGAR_KOKORO_VOICE", "bm_lewis")
KOKORO_SPEED = float(_env("VAGAR_KOKORO_SPEED", "1.0"))

# --- models (Ollama, local) ---
OLLAMA_URL = _env("VAGAR_OLLAMA_URL", "http://localhost:11434/v1")
OLLAMA_MODEL = _env("VAGAR_OLLAMA_MODEL", "qwen2.5:0.5b")
OLLAMA_DEEP_MODEL = _env("VAGAR_OLLAMA_DEEP_MODEL", "qwen2.5:3b")
VISION_MODEL = _env("VAGAR_VISION_MODEL", "moondream")

# --- speech recognition ---
WHISPER_MODEL = _env("VAGAR_WHISPER_MODEL", "base.en")
WHISPER_LANG = _env("VAGAR_WHISPER_LANG", "en")

# --- LiveKit ---
LIVEKIT_URL = _env("VAGAR_LIVEKIT_URL", "ws://127.0.0.1:7880")

# --- optional: external art/project directories ---
BOOK_DIR = _env("VAGAR_BOOK_DIR", str(VAGAR_HOME / "book_images"))

# --- weather (morning briefing) ---
# City name for wttr.in, e.g. "Austin,Texas". Blank = skip weather.
WEATHER_LOCATION = _env("VAGAR_WEATHER_LOCATION", "")
# Coordinates for the Open-Meteo fallback (decimal degrees).
WEATHER_LAT = _env("VAGAR_WEATHER_LAT", "")
WEATHER_LON = _env("VAGAR_WEATHER_LON", "")


def ensure_data_dir() -> Path:
    """Create the data directory if missing. Returns its path."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    return DATA_DIR

# --- flight recorder (local JSONL run tracing) ---
FLIGHT_RECORDER_DIR = Path(
    _env("VAGAR_FLIGHT_LOG_DIR",
         str(DATA_DIR / "flight-recorder" / "sessions"))
)

# --- recurring routines ---
ROUTINES_PATH = DATA_DIR / "routines.json"

# --- vision (YOLOv8 object detection) ---
# Place yolov8n.pt here (or point VAGAR_YOLO_MODEL at it); weights are
# downloaded once from the ultralytics release, ~6MB.
YOLO_MODEL_PATH = Path(
    _env("VAGAR_YOLO_MODEL", str(VAGAR_HOME / "models" / "yolov8n.pt"))
)

