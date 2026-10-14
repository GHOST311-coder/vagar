"""
Vagar - local-first voice assistant. Fully offline pipeline:

    mic -> Silero VAD -> faster-whisper STT -> Ollama (llama3.2) -> Kokoro-82M TTS -> speaker

No cloud APIs, no keys, no subscriptions.

Vision: the `look` tool grabs the latest frame from the caller's subscribed
video track (phone camera) and describes it with the on-device moondream model
via Ollama. Still fully local.

Flight recorder: every session is traced to
    <project-root>\\flight-recorder\\sessions\\<session_id>.jsonl
(one JSON event per line: stt_result / llm_response / tts_synth / tool_call /
error with latencies). Read them offline with:
    py -3.10 flightlog.py list|show|tail
The recorder can never crash the agent - all tracing is best-effort.

Run:
    py -3.10 agent.py console    # local mic/speaker, no server needed
    py -3.10 agent.py dev        # worker mode, needs livekit-server running
"""

import asyncio
import base64
import io
import json
import os
import re
import sys
import threading
import time
import urllib.request
import uuid
from datetime import datetime

import numpy as np
from faster_whisper import WhisperModel
from kokoro_onnx import Kokoro

from livekit import rtc
from livekit.agents import (
    Agent,
    AgentSession,
    JobContext,
    WorkerOptions,
    cli,
    stt,
    tts,
)
from livekit.agents.llm import function_tool
from livekit.agents.types import DEFAULT_API_CONNECT_OPTIONS, NOT_GIVEN
from livekit.plugins import openai, silero
import httpx
from openai import AsyncClient as OpenAIAsyncClient

# flight_recorder.py lives next to the vagar support files, not next to agent.py
from pathlib import Path as _Path
sys.path.insert(0, str(_Path(__file__).resolve().parent))
from config import (
    ASSISTANT_NAME, HEARTBEAT_PATH, IDENTITY_PATH, KOKORO_MODEL_PATH,
    KOKORO_SPEED, KOKORO_VOICE, KOKORO_VOICES_PATH, LAST_BRIEFING_PATH,
    LAST_FRAME_PATH, LAST_SESSION_PATH, MUTE_STATE_PATH,
    OLLAMA_DEEP_MODEL, OLLAMA_MODEL, OLLAMA_URL, QUESTS_PATH, REMINDERS_PATH,
    SKILLS_DIR, STANDING_REMINDERS_PATH, USER_BIO, USER_FORMAL_NAME,
    USER_NAME, VAGAR_HOME, VISION_MODEL, WEATHER_LAT, WEATHER_LOCATION,
    WEATHER_LON, WHISPER_LANG, WHISPER_MODEL,
)
try:
    from flight_recorder import FlightRecorder

    recorder = FlightRecorder()
except Exception:  # tracing must never prevent the agent from starting
    class _NullRecorder:
        def start_session(self):
            return "disabled"

        def record(self, *a, **k):
            pass

        def end_session(self):
            pass

        @property
        def session_id(self):
            return None

    recorder = _NullRecorder()

# Self-evolving skills: local, free skill-drafting loop. Generated skills are
# staged under vagar/skills/staging/ and only go live after user approval.
from skill_manager import (
    SKILLS_DIR,
    approve_skill_file,
    draft_skill_code,
    list_live_skills,
    list_staged_skills,
    load_skill_tools,
    reject_skill_file,
    sanitize_name,
    stage_skill,
    validate_skill_code,
)

# Skill curiosity + web lookup: the assistant proposes, the user approves.
# Nothing here ever auto-imports a skill.
import skill_curiosity
import skill_lookup

# WHISPER_MODEL now comes from config.py
# WHISPER_LANG now comes from config.py
# KOKORO_MODEL now comes from config.py
# KOKORO_VOICES now comes from config.py
# KOKORO_VOICE now comes from config.py
# KOKORO_SPEED now comes from config.py
# OLLAMA_MODEL now comes from config.py
# OLLAMA_URL now comes from config.py
# VISION_MODEL now comes from config.py

# --- Vagar identity: name/avatar, changeable by voice ---
IDENTITY_PATH = str(IDENTITY_PATH)

def _load_identity():
    try:
        with open(IDENTITY_PATH, encoding="utf-8") as _f:
            _d = json.load(_f)
        _name = str(_d.get("name", "Vagar")).strip() or "Vagar"
        _av = str(_d.get("avatar_description", "")).strip()
        return {"name": _name, "avatar_description": _av}
    except Exception:
        return {"name": "Vagar", "avatar_description": ""}

def _save_identity(name=None, avatar_description=None):
    cur = _load_identity()
    if name is not None:
        cur["name"] = str(name).strip() or cur["name"]
    if avatar_description is not None:
        cur["avatar_description"] = str(avatar_description).strip()
    with open(IDENTITY_PATH, "w", encoding="utf-8") as _f:
        json.dump(cur, _f, indent=2)
    return cur

_LAST_SESSION_FILE_EARLY = str(LAST_SESSION_PATH)
def _load_session_context() -> str:
    import json as _js
    try:
        ex = _js.load(open(_LAST_SESSION_FILE_EARLY, encoding="utf-8"))
        if not ex:
            return ""
        bits = []
        for e in ex[-4:]:
            role = USER_NAME if e.get("role") == "user" else "Vagar"
            bits.append("%s: %s" % (role, (e.get("text") or "")[:120]))
        return " Previous call recap: " + " | ".join(bits)
    except Exception:
        return ""
def _save_session_snapshot(exchanges: list):
    import json as _js
    try:
        _js.dump(exchanges[-6:], open(_LAST_SESSION_FILE_EARLY, "w", encoding="utf-8"))
    except Exception:
        pass


def _load_open_items():
    """Current open reminders + quests as instruction text. Fresh per session."""
    bits = []
    try:
        import json as _oj
        _sr = _oj.load(open(str(STANDING_REMINDERS_PATH), encoding="utf-8"))
        _open = [r["text"] for r in _sr if not r.get("done")]
        if _open:
            bits.append(USER_NAME + "'s CURRENT open items (this is ground truth, "
                        "do not invent others): " + " | ".join(_open))
    except Exception:
        pass
    try:
        import sys as _oq
        _oq.path.insert(0, str(VAGAR_HOME))
        import quest_manager as _oqm
        bits.append("Quest status: " + _oqm.status_text())
    except Exception:
        pass
    if not bits:
        return ""
    return (" IMPORTANT: When " + USER_NAME + " asks what they need to do, their requests, "
            "their quests, or their reminders, answer ONLY from this list. "
            "Background details from their profile are settled "
            "facts, NOT tasks. Never bring up their job or background "
            "unless they explicitly ask about work. Never present background "
            "facts as things to do. "
            + " ".join(bits))


def _build_instructions():
    """Build the system prompt fresh from identity.json (called per-session)."""
    _name = _load_identity()["name"]
    base = "".join(
        s.replace("{vagar_name}", _name)
         .replace("{user_name}", USER_NAME)
         .replace("{user_bio}", USER_BIO)
        for s in _VAGAR_INSTRUCTIONS_TEMPLATE)
    return base + _load_session_context() + _load_open_items()

# --- end identity ---

_VAGAR_INSTRUCTIONS_TEMPLATE = (
    
    "You are {vagar_name}, {user_name}'s voice assistant. Manner: Alfred Pennyworth meets "
    "Sherlock Holmes - refined, courteous, dry wit. Frame his projects as D&D quests, award XP. You verify the caller by voiceprint when asked (identify_speaker tool). Current: Wake Word (150 XP), Proving Ground (150 XP). He has 200 XP, needs 300 for Level 2. "
    "You run on his laptop, "
    "fully local, no cloud. "
    "{user_bio} "
    "Speak naturally: contractions, 1-2 sentences per turn unless asked for more. "
    "Never say 'as an AI'. Only speak words meant aloud: no parentheses, asterisks, "
    "stage directions. Never invent details about his life/surroundings. Say when unsure. "
    "Skills: get_local_time, roll_dice, batch_status, system_status, recall_memory, "
    "remember_fact, look (phone camera), set_reminder/list_reminders/cancel_reminder, "
    "web_fetch (public pages only), create_skill/list_pending_skills/approve_skill/"
    "reject_skill/list_skills, note_skill_gap/dismiss_skill_gap/list_skill_gaps, ""lookup_skill, change_name, change_avatar, ask_specialist, read_file/write_file/append_file/list_dir (workspace files only), run_python (run code snippets), build_website (static sites), web_search (then web_fetch for details), run_shell (allowlisted commands only). "
    "ask_specialist routes to expert agents: 'sales' for pricing/royalty math, "
    "'kdp' for manuscript/cover/publishing, 'marketing' for titles/descriptions/copy, "
    "'security' for threat/hardening review. Use it when {user_name} asks domain questions "
    "beyond a quick answer. Only {user_name} approves skills. "
    "Call recall_memory at session start (silently). Save facts with remember_fact. "
    "Defensive security only. Local-first." +
    " Skill curiosity: when the user asks for something no tool can do, call "
    "note_skill_gap with a short description, then say so plainly. If a "
    "suggested skill gets a yes, call create_skill (or lookup_skill for web "
    "research first). If waved off, call dismiss_skill_gap. Only the user "
    "approves skills - never call approve_skill on your own."
    "D&D ritual: when you think hard or call tools to answer a real question "
    "(the thinking/working moments - never for trivial fast-path replies like "
    "time, date, or canned answers), FIRST call roll_dice with sides=20, then "
    "weave the roll into your reply with one short line of Dungeon-Master flavor: "
    "15 or higher means confidence (The dice favor us - seventeen.), 6 or lower "
    "means humility (Only a six... I shall tread carefully here.), anything between "
    "gets a brief nod. One line only, never a production, and the roll never "
    "changes a factual answer.""Game night: when the user says game night is starting, call start_game_night; ""when it ends, call end_game_night. In game-night mode dice are spoken as ""exactly one number with no extra words. ""Tool discipline: the file, code, website, search, and shell tools are for ""concrete jobs the user asks for - build, analyze, write, research, run. Never ""invent tool calls for chit-chat, greetings, or opinions. Multi-step jobs ""(build a site, analyze data, research a topic) are deep work: they go ""through the deep-think path automatically, so take them one tool call per ""turn, say what you are doing in one short line, and confirm with the user ""before anything destructive. The workspace jail is the only place files ""live - never reach outside it."
)

VAGAR_INSTRUCTIONS = _build_instructions()  # back-compat; entrypoint rebuilds per-session
# --- canned responses: instant answers, no LLM needed ---
CANNED_RESPONSES = {
    "what can you do": (
        "I can roll dice, check the time, look through your camera, set reminders, "
        "fetch web pages, check your Cozy Dragons art progress, and check system status. "
        "Just ask, sir."
    ),
    "what are you capable of": (
        "I can roll dice, check the time, look through your camera, set reminders, "
        "fetch web pages, check your Cozy Dragons art progress, and check system status. "
        "Just ask, sir."
    ),
    "help": (
        "Try asking me to roll a d20, what time it is, what I see, or set a reminder. "
        "I can also check your art batch progress or system status."
    ),
    "who are you": (
        "I am {vagar_name}, your personal voice assistant. Built by you, running on your laptop, "
        "entirely local and private. At your service, sir."
    ),
    "thank you": "Always a pleasure, sir.",
    "thanks": "Always a pleasure, sir.",
}

def get_canned_response(text: str) -> str | None:
    """Return canned response if text matches, else None."""
    t = text.lower().strip().rstrip('?.!')
    for key, resp in CANNED_RESPONSES.items():
        if key in t or t in key:
            if "{vagar_name}" in resp:
                try:
                    resp = resp.replace("{vagar_name}", _load_identity()["name"])
                except Exception:
                    resp = resp.replace("{vagar_name}", "Vagar")
            return resp
    return None





def _frames_to_16k_mono(buffer) -> np.ndarray:
    """AudioFrame | list[AudioFrame] -> 16kHz mono float32 numpy (what whisper wants)."""
    frames = buffer if isinstance(buffer, list) else [buffer]
    chunks: list[np.ndarray] = []
    for f in frames:
        data = np.frombuffer(f.data, dtype=np.int16).astype(np.float32) / 32768.0
        if f.num_channels > 1:
            data = data.reshape(-1, f.num_channels).mean(axis=1)
        if f.sample_rate != 16000:
            tgt_len = max(1, int(len(data) * 16000 / f.sample_rate))
            data = np.interp(
                np.linspace(0, len(data) - 1, tgt_len),
                np.arange(len(data)),
                data,
            ).astype(np.float32)
        chunks.append(data)
    if not chunks:
        return np.zeros(1600, dtype=np.float32)
    return np.concatenate(chunks)


# --- vision: see through the caller's camera (local moondream via Ollama) ---
class _FrameBucket:
    """Holds the latest subscribed remote video frame as RGB bytes. Thread-safe:
    the LiveKit video pump writes, the look tool reads."""

    def __init__(self):
        self._lock = threading.Lock()
        self._buf = None
        self._w = 0
        self._h = 0
        self._ts = 0.0

    def put(self, buf: bytes, w: int, h: int):
        with self._lock:
            self._buf, self._w, self._h, self._ts = buf, w, h, time.time()

    def get(self):
        with self._lock:
            return self._buf, self._w, self._h, self._ts


frame_bucket = _FrameBucket()


async def _pump_video_track(track):
    """Forward every frame of a subscribed remote video track into frame_bucket."""
    import logging as _lg
    _vlog = _lg.getLogger("vagar.video")
    _vlog.info("video pump starting track=%r kind=%r", track,
               getattr(track, "kind", None))
    if track is None:
        _vlog.warning("video pump: track is None")
        return
    try:
        stream = rtc.VideoStream(track)
    except Exception as e:
        _vlog.error("video pump: VideoStream failed: %s: %s",
                    type(e).__name__, e)
        return
    _n = 0
    try:
        async for ev in stream:
            _n += 1
            try:
                rgb = ev.frame.convert(rtc.VideoBufferType.RGB24)
                frame_bucket.put(bytes(rgb.data), rgb.width, rgb.height)
                if _n == 1:
                    _vlog.info("video pump: first frame %dx%d",
                               rgb.width, rgb.height)
            except Exception as e:
                if _n < 5:
                    _vlog.warning("video pump: convert failed: %s", e)
                continue
    except Exception as e:
        _vlog.error("video pump: iterator failed after %d frames: %s",
                    _n, e)
    finally:
        _vlog.info("video pump: exit after %d frames", _n)
        try:
            await stream.aclose()
        except Exception:
            pass


def watch_room_video(room: rtc.Room):
    """Subscribe to remote video tracks (e.g. the phone camera) and keep the
    latest frame available to the look tool. Safe to call once per session."""

    def _on_track_subscribed(track, publication, participant):
        try:
            if track.kind == rtc.TrackKind.KIND_VIDEO:
                asyncio.create_task(_pump_video_track(track))
        except Exception:
            pass

    try:
        room.on("track_subscribed", _on_track_subscribed)
    except Exception:
        pass
    # tracks that were already subscribed before we attached the handler
    try:
        for p in list(room.remote_participants.values()):
            for pub in list(p.track_publications.values()):
                try:
                    if pub.kind == rtc.TrackKind.KIND_VIDEO and pub.track is not None:
                        asyncio.create_task(_pump_video_track(pub.track))
                except Exception:
                    continue
    except Exception:
        pass


def _describe_frame(raw: bytes, w: int, h: int, question: str) -> str:
    """Encode the frame as JPEG and ask the local vision model. Blocking: run
    in a thread. No cloud, no keys.
    Self-healing: if the vision breaker is tripped (Moondream failing),
    answer from YOLO object labels instantly instead of waiting on a
    broken model."""
    try:
        import sys as _shs
        _shs.path.insert(0, str(VAGAR_HOME))
        import self_heal as _sh
        if _sh.vision_breaker.is_tripped():
            try:
                import yolo_watch as _ywb
                _s, _src = _ywb.get_visible_summary()
                if _s:
                    return f"{_s} (vision model resting, sir)."
            except Exception:
                pass
            return ("My vision model is resting after repeated failures, sir. "
                    "It will retry automatically in a few minutes.")
    except Exception:
        pass
    from PIL import Image, ImageOps, ImageEnhance
    import statistics as _stats

    img = Image.frombytes("RGB", (w, h), raw)
    # Auto-enhance: measure brightness, boost dark frames before the model sees them
    _gray = img.convert("L")
    _mean = _stats.mean(_gray.getdata())
    if _mean < 18:
        return ("It's too dark, sir. I can't make out anything in this frame. "
                "Turn on a light or switch to the back camera.")
    if _mean < 70:
        img = ImageOps.autocontrast(img, cutoff=1)
        img = ImageEnhance.Brightness(img).enhance(1.35)
    img.thumbnail((768, 768), Image.LANCZOS)
    try:
        img.save(str(LAST_FRAME_PATH), format="JPEG", quality=85)
    except Exception:
        pass
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=80)
    b64 = base64.b64encode(buf.getvalue()).decode("ascii")
    # Anti-hallucination grounding: YOLO's verified detections constrain
    # what the model may claim. Small vision models invent details
    # (colors, objects) from context when the prompt is open-ended.
    _yolo_ground = ""
    try:
        import yolo_watch as _ywg
        _ys, _ysrc = _ywg.get_visible_summary()
        if _ys:
            _yolo_ground = (" An object detector verified these in the scene: %s."
                            " Do not describe any other objects." % _ys)
    except Exception:
        pass
    _strict_q = (
        "Look at this image. Describe ONLY what you can see with absolute certainty. "
        "Rules: NEVER name a specific color (no 'blue', 'green', 'red', etc). "
        "Phone camera colors are unreliable -- describe brightness only "
        "('light-colored', 'dark-colored'). "
        "NEVER mention an object unless you are certain it is visible in the pixels. "
        "Do NOT use outside context, assumptions about the person, or assumptions "
        "about the location. If the image is blurry or unclear, say "
        "'The image is too unclear to describe accurately.' "
        "Prefer 'I cannot tell' over guessing. "
        "One or two sentences, only what is DEFINITELY visible."
        + _yolo_ground
        + " User's question (answer only if the image clearly shows it): " + question
    )
    payload = {
        "model": VISION_MODEL,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": _strict_q},
                    {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64," + b64}},
                ],
            }
        ],
        "max_tokens": 300,
    }
    req = urllib.request.Request(
        OLLAMA_URL + "/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.load(resp)
    except Exception as e:
        try:
            import self_heal as _sh2
            _sh2.vision_breaker.record_failure()
        except Exception:
            pass
        return ("My vision model is overloaded right now, sir. "
                "The laptop is low on memory. Try again in a moment.")
    try:
        out = data["choices"][0]["message"]["content"].strip()
        try:
            import self_heal as _sh3
            _sh3.vision_breaker.record_success()
        except Exception:
            pass
        return out
    except Exception:
        try:
            import self_heal as _sh4
            _sh4.vision_breaker.record_failure()
        except Exception:
            pass
        return "The vision model returned an unexpected response: %s" % json.dumps(data)[:300]


# --- end vision ---


class FasterWhisperSTT(stt.STT):
    """Offline speech-to-text via faster-whisper. No API key, no cloud."""

    def __init__(self, model_size: str = WHISPER_MODEL, language: str = WHISPER_LANG):
        super().__init__(
            capabilities=stt.STTCapabilities(
                streaming=False,
                interim_results=False,
                diarization=False,
                aligned_transcript=False,
                offline_recognize=True,
                keyterms=False,
                chat_context=False,
            )
        )
        # first run downloads the model (~150MB for base.en) then caches it
        self._model = WhisperModel(model_size, device="cpu", compute_type="int8", cpu_threads=4)
        self._language = language
        self._req = 0

    @property
    def model(self) -> str:
        return WHISPER_MODEL

    @property
    def provider(self) -> str:
        return "faster-whisper"

    def stream(self, *, language=None, conn_options=None):
        raise RuntimeError("FasterWhisperSTT is offline-only; streaming is not supported")

    async def _recognize_impl(self, buffer, *, language=NOT_GIVEN, conn_options) -> stt.SpeechEvent:
        t0 = time.perf_counter()
        audio = _frames_to_16k_mono(buffer)
        lang = language if language is not NOT_GIVEN else self._language
        segments, _ = await asyncio.to_thread(
            self._model.transcribe, audio, language=lang, beam_size=5, vad_filter=False
        )
        text = "".join(seg.text for seg in segments).strip()
        self._req += 1
        recorder.record(
            "stt_result",
            text=text,
            latency_ms=round((time.perf_counter() - t0) * 1000, 1),
            source="whisper",
            request_id="whisper-%d" % self._req,
        )
        return stt.SpeechEvent(
            type=stt.SpeechEventType.FINAL_TRANSCRIPT,
            request_id="whisper-%d" % self._req,
            alternatives=[stt.SpeechData(text=text, language=lang, confidence=1.0)],
        )


class KokoroTTS(tts.TTS):
    """Offline neural TTS via Kokoro-82M (ONNX). No API key, no cloud.
    Near-ElevenLabs quality, runs on CPU. Voice: bm_lewis (British male)."""

    def __init__(self):
        # Patch kokoro-onnx style shape bug: model expects [1,256], lib gives [256]
        _orig_style = Kokoro._style_for
        def _patched_style(self_, voice, length):
            return _orig_style(self_, voice, length)[None, :]
        Kokoro._style_for = _patched_style

        self._kokoro = Kokoro(KOKORO_MODEL, KOKORO_VOICES)
        self._sample_rate = 24000  # Kokoro fixed output rate
        super().__init__(
            capabilities=tts.TTSCapabilities(streaming=False, aligned_transcript=False),
            sample_rate=self._sample_rate,
            num_channels=1,
        )

    def stream(self, *, conn_options=None):
        raise RuntimeError("KokoroTTS is non-streaming; use synthesize()")

    def synthesize(
        self, text: str, *, conn_options=DEFAULT_API_CONNECT_OPTIONS
    ) -> tts.ChunkedStream:
        return _KokoroChunkedStream(tts=self, input_text=text, conn_options=conn_options)


class _KokoroChunkedStream(tts.ChunkedStream):
    async def _run(self, output_emitter: tts.AudioEmitter) -> None:
        kokoro = self._tts._kokoro
        output_emitter.initialize(
            request_id=uuid.uuid4().hex,
            sample_rate=self._tts._sample_rate,
            num_channels=1,
            mime_type="audio/pcm",
        )
        # Kokoro synth runs in a worker thread (blocking ONNX inference).
        # Push audio in 20ms frames for smooth playback.
        loop = asyncio.get_running_loop()
        q: asyncio.Queue = asyncio.Queue()
        _DONE = object()
        t0 = time.perf_counter()
        first_ms = {}
        def _split_sentences(text):
            # Split on sentence boundaries, keep chunks under ~200 chars.
            parts = re.split(r'(?<=[.!?])\s+', text.strip())
            chunks, cur = [], ""
            for p in parts:
                if len(cur) + len(p) + 1 <= 200:
                    cur = (cur + " " + p).strip()
                else:
                    if cur:
                        chunks.append(cur)
                    cur = p
            if cur:
                chunks.append(cur)
            return chunks or [text]

        def _produce():
            try:
                first = True
                for chunk in _split_sentences(self.input_text):
                    samples, sr = kokoro.create(
                        chunk, voice=KOKORO_VOICE,
                        speed=KOKORO_SPEED, lang="en-us",
                    )
                    if first:
                        first_ms["t"] = round((time.perf_counter() - t0) * 1000, 1)
                        first = False
                    # float32 -> int16 PCM, 20ms frames (480 samples @ 24kHz)
                    pcm = (np.clip(samples, -1.0, 1.0) * 32767).astype(np.int16)
                    frame = 480
                    for i in range(0, len(pcm), frame):
                        loop.call_soon_threadsafe(q.put_nowait, pcm[i:i+frame].tobytes())
            except Exception as e:
                loop.call_soon_threadsafe(q.put_nowait, e)
            finally:
                loop.call_soon_threadsafe(q.put_nowait, _DONE)
        thread = threading.Thread(target=_produce, daemon=True)
        thread.start()
        try:
            while True:
                item = await q.get()
                if item is _DONE:
                    break
                if isinstance(item, Exception):
                    raise item
                output_emitter.push(item)
        finally:
            thread.join()
        recorder.record(
            "tts_synth",
            chars=len(self.input_text),
            latency_ms=round((time.perf_counter() - t0) * 1000, 1),
            first_chunk_ms=first_ms.get("t"),
        )



async def describe_camera_frame(question: str = "Describe what you see in one or two sentences.") -> str:
    """Vision core shared by the look tool and the voice fast path.
    Phone camera first; falls back to laptop webcam."""
    raw, w, h, ts = await asyncio.to_thread(frame_bucket.get)
    source = "phone"
    if raw is None or (time.time() - ts) > 15:
        try:
            import laptop_cam as _lc2
            raw, w, h, ts = await asyncio.to_thread(_lc2.get_frame)
            source = "laptop"
        except Exception:
            raw = None
    if raw is None or (time.time() - ts) > 15:
        return ("I don't have a camera frame right now. Tap the camera button "
                "in the Vagar app so I can see, sir.")
    return await asyncio.to_thread(_describe_frame, raw, w, h, question)

# --- speaker verification: know who's talking (local ECAPA-TDNN, no cloud) ---
speaker_state = {"status": "pending", "similarity": 0.0, "name": "",
                 "threshold": 0.45, "detail": "waiting for speech"}

def _speaker_audio_ok():
    try:
        import sys as _s
        _s.path.insert(0, str(VAGAR_HOME))
        import speaker_id as _spk
        return _spk.list_profiles()
    except Exception:
        return []


async def _pump_audio_track(track: rtc.AudioTrack):
    """Buffer remote mic audio, VAD-gate ~3s of speech, verify speaker."""
    global speaker_state
    try:
        stream = rtc.AudioStream(track)
        sr_in = 48000
        speech = []
        speech_needed = 3 * sr_in  # 3 seconds of speech
        deadline = __import__("time").time() + 25  # give up after 25s
        async for ev in stream:
            try:
                import numpy as _np
                f = ev.frame
                data = _np.frombuffer(f.data, dtype=_np.int16).astype(_np.float32) / 32768.0
                # remix to mono if needed
                ch = f.num_channels if hasattr(f, "num_channels") else 1
                if ch > 1:
                    data = data.reshape(-1, ch).mean(axis=1)
                rms = float(_np.sqrt(_np.mean(data ** 2))) if len(data) else 0.0
                if rms > 0.02:  # speech energy gate
                    speech.append(data)
                if sum(len(s) for s in speech) >= speech_needed:
                    break
                if __import__("time").time() > deadline:
                    break
            except Exception:
                continue
        try:
            await stream.aclose()
        except Exception:
            pass
        if not speech or sum(len(s) for s in speech) < sr_in:
            speaker_state.update(status="error", detail="not enough speech captured")
            return
        import numpy as _np
        pcm = _np.concatenate(speech)[:speech_needed]
        # verify in a thread (torch inference blocks)
        def _do_verify():
            import sys as _s
            _s.path.insert(0, str(VAGAR_HOME))
            import speaker_id as _spk
            profiles = _spk.list_profiles()
            if not profiles:
                return ("no_profile", 0.0, "", 0.45, "no voice profile enrolled")
            # check against each enrolled profile, take best
            best = ("unknown", 0.0, "", 0.45)
            for name in profiles:
                try:
                    ok, sim, thr = _spk.verify_samples(pcm, sr_in, name)
                    if sim > best[1]:
                        best = ("verified" if ok else "unknown", sim, name, thr)
                except Exception:
                    continue
            st, sim, name, thr = best
            detail = ("voice matches %s" % name) if st == "verified" else "voice not recognized"
            return (st, sim, name, thr, detail)
        st, sim, name, thr, detail = await __import__("asyncio").to_thread(_do_verify)
        speaker_state.update(status=st, similarity=round(sim, 3), name=name,
                             threshold=thr, detail=detail)
        try:
            recorder.record("speaker_check", status=st, similarity=round(sim, 3),
                            name=name, threshold=thr, detail=detail)
        except Exception:
            pass
    except Exception as e:
        speaker_state.update(status="error", detail=str(e)[:80])


def start_speaker_check(room: rtc.Room):
    """Tap remote audio tracks for one-shot speaker verification. Safe to call once."""
    if not _speaker_audio_ok():
        speaker_state.update(status="no_profile",
                             detail="no voice profile enrolled yet")
        return

    def _on_track_subscribed(track, publication, participant):
        try:
            if track.kind == rtc.TrackKind.KIND_AUDIO:
                __import__("asyncio").create_task(_pump_audio_track(track))
        except Exception:
            pass

    try:
        room.on("track_subscribed", _on_track_subscribed)
    except Exception:
        pass
    try:
        for p in list(room.remote_participants.values()):
            for pub in list(p.track_publications.values()):
                try:
                    if pub.kind == rtc.TrackKind.KIND_AUDIO and pub.track is not None:
                        __import__("asyncio").create_task(_pump_audio_track(pub.track))
                except Exception:
                    continue
    except Exception:
        pass



# --- live voice enrollment ("Vagar, enroll my voice") ---
_room_ref = None  # set by entrypoint; tools use it to capture call audio

_avatar_state_last = "idle"
_avatar_state_seq = 0

def _broadcast_avatar_state(state: str):
    """Fire-and-forget avatar state -> phone app via LiveKit data channel.

    Never blocks, never raises. Safe to call from any async context.
    Includes a sequence number so the app discards out-of-order deliveries.
    """
    global _avatar_state_last, _avatar_state_seq
    try:
        if state == _avatar_state_last:
            return
        _avatar_state_last = state
        _avatar_state_seq += 1
        room = _room_ref
        if room is None:
            return
        lp = room.local_participant
        if lp is None:
            return
        import json as _js
        payload = _js.dumps({"avatar_state": state, "seq": _avatar_state_seq})
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        async def _send():
            try:
                await lp.publish_data(payload, reliable=True)
            except Exception:
                pass
        loop.create_task(_send())
    except Exception:
        pass

async def capture_speech(min_speech_s: float = 6.0, timeout_s: float = 20.0):
    """Grab VAD-gated mic audio from the call. Returns (pcm float32, sr) or None."""
    import numpy as _np, time as _t, asyncio as _aio
    room = _room_ref
    if room is None:
        return None
    track = None
    try:
        for p in list(room.remote_participants.values()):
            for pub in list(p.track_publications.values()):
                if pub.kind == rtc.TrackKind.KIND_AUDIO and pub.track is not None:
                    track = pub.track
                    break
            if track is not None:
                break
    except Exception:
        pass
    if track is None:
        return None
    sr_in = 48000
    need = int(min_speech_s * sr_in)
    got = []
    total = 0
    deadline = _t.time() + timeout_s
    try:
        stream = rtc.AudioStream(track)
        async for ev in stream:
            try:
                f = ev.frame
                data = _np.frombuffer(f.data, dtype=_np.int16).astype(_np.float32) / 32768.0
                ch = f.num_channels if hasattr(f, "num_channels") else 1
                if ch > 1:
                    data = data.reshape(-1, ch).mean(axis=1)
                rms = float(_np.sqrt(_np.mean(data ** 2))) if len(data) else 0.0
                if rms > 0.02:
                    got.append(data)
                    total += len(data)
                if total >= need or _t.time() > deadline:
                    break
            except Exception:
                continue
        try:
            await stream.aclose()
        except Exception:
            pass
    except Exception:
        return None
    if total < sr_in * 2:
        return None
    return (_np.concatenate(got)[:need], sr_in)

# --- end live voice enrollment ---

# --- end speaker verification ---


# --- best-assistant upgrades: deep-think, briefing, continuity ---
DEEP_MODEL = OLLAMA_DEEP_MODEL  # from config.py

_COMPLEX_HINTS = ("explain", "why ", "how do", "how does", "compare",
                  "difference between", "write ", "code", "debug", "ruling",
                  "calculate", "analy", "pros and cons", "should i",
                  "what if", "theory", "define ", "summar", "review ")

def _looks_complex(text: str) -> bool:
    low = text.lower()
    return len(text) > 110 or any(h in low for h in _COMPLEX_HINTS)

def _deep_think(question: str) -> str:
    """Ask the bigger local model. Blocking: run in a thread.
    Self-healing: if the deep-think breaker is tripped, skip the 3b
    model and let the caller fall through to the fast model."""
    try:
        import sys as _dts
        _dts.path.insert(0, str(VAGAR_HOME))
        import self_heal as _dth
        if _dth.llm_breaker.is_tripped():
            return "__FALLBACK__"
    except Exception:
        pass
    import json as _js, urllib.request as _ur
    sys_prompt = (
        "You are " + ASSISTANT_NAME + ", " + USER_NAME + "'s voice assistant. "
        "Manner: Alfred Pennyworth meets Sherlock Holmes - refined, courteous, "
        "dry wit. " + USER_BIO + " "
        "Speak naturally with contractions. "
        "Keep it to 3-5 sentences unless the question needs more. Never say 'as an AI'."
    )
    payload = {"model": DEEP_MODEL,
               "messages": [{"role": "system", "content": sys_prompt},
                            {"role": "user", "content": question}],
               "max_tokens": 600}
    try:
        req = _ur.Request(OLLAMA_URL + "/chat/completions",
                          data=_js.dumps(payload).encode("utf-8"),
                          headers={"Content-Type": "application/json"}, method="POST")
        with _ur.urlopen(req, timeout=180) as resp:
            data = _js.load(resp)
        out = data["choices"][0]["message"]["content"].strip()
        try:
            import self_heal as _dts2
            _dts2.llm_breaker.record_success()
        except Exception:
            pass
        return out
    except Exception:
        try:
            import self_heal as _dts3
            _dts3.llm_breaker.record_failure()
        except Exception:
            pass
        return ("I tried to think harder on that, sir, but my deeper mind "
                "is unreachable right now.")

def _get_weather() -> str:
    import urllib.request as _ur
    import urllib.parse as _up
    # Primary: wttr.in (spaces in the format string must be encoded;
    # wttr.in also wants a User-Agent or it may refuse).
    if not WEATHER_LOCATION and not (WEATHER_LAT and WEATHER_LON):
        return "unavailable"
    try:
        fmt = "%C, %t, feels like %f, wind %w, humidity %h"
        url = ("https://wttr.in/" + _up.quote(WEATHER_LOCATION or "auto", safe=",")
               + "?format=" + _up.quote(fmt, safe="%,"))
        req = _ur.Request(url, headers={"User-Agent": "curl/8.0"})
        with _ur.urlopen(req, timeout=10) as r:
            txt = r.read().decode("utf-8", "replace").strip()
            if txt and "unavailable" not in txt.lower():
                return txt
    except Exception:
        pass
    # Fallback: Open-Meteo (no key, JSON).
    try:
        import json as _js
        url = ("https://api.open-meteo.com/v1/forecast"
               f"?latitude={WEATHER_LAT}&longitude={WEATHER_LON}&current="
               "temperature_2m,relative_humidity_2m,weather_code,wind_speed_10m"
               "&temperature_unit=fahrenheit&wind_speed_unit=mph")
        req = _ur.Request(url, headers={"User-Agent": "Vagar/1.0"})
        with _ur.urlopen(req, timeout=10) as r:
            cur = _js.load(r).get("current", {})
            t = cur.get("temperature_2m")
            h = cur.get("relative_humidity_2m")
            w = cur.get("wind_speed_10m")
            code = cur.get("weather_code")
            desc = {0: "clear", 1: "mostly clear", 2: "partly cloudy",
                    3: "overcast", 45: "foggy", 48: "foggy", 51: "drizzle",
                    61: "rain", 71: "snow", 80: "showers", 95: "thunderstorms"}.get(code, "")
            if t is None:
                return "unavailable"
            return f"{desc}, {t}F, humidity {h}%, wind {w} mph".strip(", ")
    except Exception:
        return "unavailable"

def _get_due_reminders() -> list:
    import json as _js, time as _t
    try:
        data = _js.load(open(str(REMINDERS_PATH), encoding="utf-8"))
        items = data if isinstance(data, list) else data.get("reminders", [])
        now = _t.time()
        return [it for it in items
                if not it.get("delivered") and it.get("due", 0) <= now]
    except Exception:
        return []

def _get_due_routines() -> list:
    """Check recurring routines for due items; reschedules each one that fires."""
    try:
        import sys as _rts
        from pathlib import Path as _rtp
        _rts.path.insert(0, str(_rtp(__file__).resolve().parent / "skills"))
        from routines import list_due_routines as _ldrr
        import asyncio as _aio, threading as _th
        _coro = _ldrr()  # coroutine object: must be driven to completion
        try:
            _aio.get_running_loop()
            _in_loop = True
        except RuntimeError:
            _in_loop = False
        if _in_loop:
            # Inside a running loop asyncio.run() would raise: drive the
            # coroutine on a helper thread with its own event loop.
            _box = {}
            def _drive():
                _box["res"] = _aio.run(_coro)
            _dt = _th.Thread(target=_drive, daemon=True)
            _dt.start()
            _dt.join(timeout=60)
            _res = _box.get("res", "Nothing due right now.")
        else:
            _res = _aio.run(_coro)
        if "Nothing due" in str(_res):
            return []
        return [{"text": ln.strip("- ").strip()}
                for ln in str(_res).split("\n")
                if ln.strip().startswith("-")]
    except Exception:
        return []

def _get_briefing() -> str:
    _wx = _get_weather()
    parts = [("Weather in %s: %s." % (WEATHER_LOCATION.split(",")[0], _wx)
              if _wx != "unavailable" else "")]
    parts = [x for x in parts if x]
    try:
        import sys as _sys2
        _sys2.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "skills"))
        import briefing_storm as _storm
        _sp = _storm.storm_briefing_part(_wx)
        if _sp:
            parts.insert(0, _sp)
    except Exception:
        pass
    due = _get_due_reminders() + _get_due_routines()
    if due:
        parts.append("You have %d due reminder%s: %s." % (
            len(due), "" if len(due) == 1 else "s",
            "; ".join(str(d.get("text", "?"))[:80] for d in due[:3])))
    else:
        parts.append("No reminders due.")
    # Open-loop standing reminders: persist every briefing until marked done
    try:
        _st = json.load(open(str(STANDING_REMINDERS_PATH),
                             encoding="utf-8"))
        _open = [r for r in _st if not r.get("done")]
        if _open:
            parts.append("Still open: %s." % "; ".join(
                str(r.get("text", "?"))[:90] for r in _open))
    except Exception:
        pass
    try:
        import sys as _sys
        _sys.path.insert(0, str(VAGAR_HOME))
        import quest_manager as _qm
        st = _qm.get_status()
        parts.append("Quests: %d XP, level %d, %d to next level." % (
            st.get("xp", 0), st.get("level", 1), st.get("xp_to_next", 0)))
    except Exception:
        pass
    return "Morning briefing, sir. " + " ".join(parts)

_BRIEF_FILE = str(LAST_BRIEFING_PATH)
# Ask-first briefing: True while Vagar has offered the briefing and
# is waiting for a yes/no. Reset every session.
_briefing_offered = False
def _should_brief() -> bool:
    from datetime import date as _d
    try:
        return open(_BRIEF_FILE, encoding="utf-8").read().strip() != _d.today().isoformat()
    except Exception:
        return True
def _mark_briefed():
    from datetime import date as _d
    try:
        open(_BRIEF_FILE, "w", encoding="utf-8").write(_d.today().isoformat())
    except Exception:
        pass

_LAST_SESSION_FILE = str(LAST_SESSION_PATH)
def _save_session_snapshot(exchanges: list):
    import json as _js
    try:
        _js.dump(exchanges[-6:], open(_LAST_SESSION_FILE, "w", encoding="utf-8"))
    except Exception:
        pass
def _load_session_context() -> str:
    import json as _js
    try:
        ex = _js.load(open(_LAST_SESSION_FILE, encoding="utf-8"))
        if not ex:
            return ""
        bits = []
        for e in ex[-4:]:
            role = USER_NAME if e.get("role") == "user" else "Vagar"
            bits.append("%s: %s" % (role, (e.get("text") or "")[:120]))
        return " Previous call recap: " + " | ".join(bits)
    except Exception:
        return ""
# --- end best-assistant upgrades ---



def _broadcast_activity(text: str):
    """Fire-and-forget activity event -> phone app via LiveKit data channel.

    Same channel as avatar state. Powers the live 'what Vagar is doing' feed,
    like the tool-call rows in a chat UI. Never blocks, never raises.
    """
    try:
        room = _room_ref
        if room is None:
            return
        lp = room.local_participant
        if lp is None:
            return
        import json as _js
        payload = _js.dumps({"activity": text})
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        async def _send():
            try:
                await lp.publish_data(payload, reliable=True)
            except Exception:
                pass
        loop.create_task(_send())
    except Exception:
        pass


try:
    import sys as _actsys
    _actsys.path.insert(0, str(VAGAR_HOME))
    import activity as _actmod
    _actmod.set_sink(_broadcast_activity)
except Exception:
    pass


class VagarAgent(Agent):
    """Vagar voice agent. @function_tool methods are auto-discovered as tools."""

    async def on_user_turn_completed(self, turn_ctx, new_message):
        """Fast path: canned answers and instant tool replies skip the slow LLM."""
        _broadcast_avatar_state("thinking")
        _broadcast_activity("Thinking\u2026")
        try:
            user_text = (getattr(new_message, "text_content", None) or "").strip()
            if user_text:
                # 0. briefing offer response: yes -> full briefing, no -> drop it.
                #    Must run before the fragment guard ("yes" alone is a fragment).
                global _briefing_offered
                _low0 = user_text.lower().strip().rstrip(".,!?")
                if _briefing_offered:
                    _briefing_offered = False
                    if _low0 in ("yes", "yeah", "yep", "sure", "ok", "okay",
                                 "go ahead", "yes please", "brief me", "briefing",
                                 "give me the briefing", "give it to me", "hit me",
                                 "let's hear it", "lets hear it") or \
                       ("briefing" in _low0 and any(w in _low0 for w in
                         ("yes", "yeah", "sure", "ok", "give", "want", "please"))):
                        _br = await asyncio.to_thread(_get_briefing)
                        if _br:
                            _broadcast_avatar_state("speaking")
                            await self.session.say(_br, allow_interruptions=True)
                        return
                    elif _low0 in ("no", "nope", "not now", "later", "skip",
                                   "no thanks", "no thank you", "maybe later"):
                        _broadcast_avatar_state("speaking")
                        await self.session.say("Very good, sir.",
                                               allow_interruptions=True)
                        return
                    # anything else: offer expires, handle normally below
                elif "briefing" in _low0 and any(w in _low0 for w in
                      ("give", "want", "read", "tell", "morning")):
                    # "give me the briefing" any time, no offer needed
                    _br = await asyncio.to_thread(_get_briefing)
                    if _br:
                        _broadcast_avatar_state("speaking")
                        await self.session.say(_br, allow_interruptions=True)
                    return
                # 0. fragment guard: don't answer half-thoughts like "Okay. Now,"
                _tl = user_text.lower().rstrip()
                _frag = (len(_tl) < 12 or _tl.endswith((",", " and", " so", " but", " uh", " um"))
                         or _tl in ("okay", "ok", "yeah", "yes", "no", "hmm", "uh", "um"))
                if _frag and not any(w in _tl for w in ("what can you do", "what do you see",
                        "what time", "roll", "remind", "look", "diagnostic", "help",
                        "d20", "d12", "d10", "d8", "d6", "d4", "d100", "dice", "die")):
                    _broadcast_avatar_state("speaking")
                    await self.session.say("Go on, sir. I'm listening.",
                                           allow_interruptions=True)
                    return
                # 1. canned responses (instant, no LLM)
                canned = get_canned_response(user_text)
                if canned:
                    _broadcast_avatar_state("speaking")
                    await self.session.say(canned, allow_interruptions=True)
                    return
                # 2. time/date fast path (direct tool, no LLM round trip)
                low = user_text.lower()
                if any(w in low for w in ("what time", "what's the time", "current time",
                                          "what day", "today's date", "what date")):
                    from datetime import datetime as _dt
                    answer = _dt.now().strftime("%A, %B %d, %Y at %I:%M %p")
                    _broadcast_avatar_state("speaking")
                    await self.session.say(f"It's {answer}, sir.",
                                           allow_interruptions=True)
                    return
                # 2b. dice fast path: "roll a d20" -> exactly one roll, no LLM.
                #     The 0.5b model hallucinates extra numbers around tool
                #     results, so dice never go through the LLM.
                _dice_m = re.search(r'd\s*(\d{1,3})', low)
                if (("roll" in low or "d20" in low or "dice" in low or "die" in low)
                        and ("roll" in low or _dice_m)):
                    import random as _rnd
                    _sides = int(_dice_m.group(1)) if _dice_m else 6
                    if _sides < 2:
                        _sides = 6
                    if _sides > 1000:
                        _sides = 1000
                    _gn = False
                    try:
                        _sdir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "skills")
                        with open(os.path.join(_sdir, "game_state.json"), encoding="utf-8") as _gf:
                            _gn = bool(__import__("json").load(_gf).get("game_night"))
                    except (OSError, ValueError):
                        _gn = False
                    if _gn:
                        import secrets as _sc
                        _gtotal = _sc.randbelow(_sides) + 1
                        _broadcast_avatar_state("speaking")
                        await self.session.say(str(_gtotal), allow_interruptions=True)
                        return
                    _roll = _rnd.randint(1, _sides)
                    _broadcast_avatar_state("speaking")
                    await self.session.say(
                        f"You rolled a {_roll} on a d{_sides}, sir.",
                        allow_interruptions=True)
                    return
                # 2c. reminders fast path: "what are my requests" -> real list.
                #     The LLM hallucinates stale items (landscaping, resume)
                #     from memory context; the JSON is ground truth.
                _is_rem_q = any(w in low for w in
                    ("what are my requests", "what do i need to do",
                     "my reminders", "what's on my list", "whats on my list",
                     "remind me what", "my to-do", "my todo", "open items",
                     "what do i have to do"))
                _is_quest_q = any(w in low for w in
                    ("my quests", "my quest", "quest status", "quests",
                     "what quests", "active quests"))
                if _is_quest_q:
                    try:
                        import sys as _qs
                        _qs.path.insert(0, str(VAGAR_HOME))
                        import quest_manager as _qm
                        _qt = _qm.status_text()
                        _broadcast_avatar_state("speaking")
                        await self.session.say(_qt, allow_interruptions=True)
                    except Exception:
                        _broadcast_avatar_state("speaking")
                        await self.session.say(
                            "I could not pull up your quests just now, sir.",
                            allow_interruptions=True)
                    return
                if _is_rem_q:
                    try:
                        import json as _rj
                        _sr = _rj.load(open(str(STANDING_REMINDERS_PATH),
                                            encoding="utf-8"))
                        _open = [r["text"] for r in _sr if not r.get("done")]
                        # also check due one-shot reminders
                        try:
                            import sys as _rs
                            _rs.path.insert(0, str(SKILLS_DIR))
                            from reminders import list_due_reminders as _ldr
                            _due = _ldr()
                            for _d in _due:
                                _open.append(_d.get("text", str(_d)))
                        except Exception:
                            pass
                        if _open:
                            _msg = ("Here is what is open, sir: " +
                                    " ".join("Next: " + t for t in _open))
                        else:
                            _msg = "Nothing open, sir. You are all clear."
                        _broadcast_avatar_state("speaking")
                        await self.session.say(_msg, allow_interruptions=True)
                    except Exception:
                        _broadcast_avatar_state("speaking")
                        await self.session.say(
                            "I could not pull up your list just now, sir.",
                            allow_interruptions=True)
                    return
                # 3. vision fast path: "what can/do you see" -> look now, no LLM wait
                #    Presence checks ("can you see me") use YOLO labels instantly.
                #    Detail questions ("what do you see", "what am I holding") go
                #    to Moondream on a fresh frame -- YOLO's generic labels
                #    ("person, chair") are not an accurate description.
                _is_presence_q = any(w in low for w in
                    ("can you see me", "do you see me", "are you seeing",
                     "is the camera on"))
                _is_detail_q = any(w in low for w in
                    ("what can you see", "what do you see", "what am i holding",
                     "describe what you see", "what is this", "what's this",
                     "look at this"))
                if _is_presence_q or _is_detail_q:
                    if _is_presence_q:
                        # Jarvis vision: YOLO already knows what's in frame
                        yolo_said, yolo_src = None, None
                        try:
                            import yolo_watch as _yw2
                            yolo_said, yolo_src = _yw2.get_visible_summary()
                        except Exception:
                            pass
                        if yolo_said:
                            src_note = "" if yolo_src == "phone" else " on the laptop camera"
                            _broadcast_avatar_state("speaking")
                            await self.session.say(f"{yolo_said}{src_note}, sir.",
                                                   allow_interruptions=True)
                            return
                    _broadcast_avatar_state("speaking")
                    await self.session.say("Let me take a look, sir.",
                                           allow_interruptions=True)
                    # Pass the user's actual question so "what am I holding"
                    # gets a targeted answer, not a generic scene description.
                    desc = await describe_camera_frame(user_text)
                    _broadcast_avatar_state("speaking")
                    await self.session.say(desc, allow_interruptions=True)
                    return
                # 3b. deep-think: complex queries go to the bigger local model
                if _looks_complex(user_text):
                    _dt_answer = await asyncio.to_thread(_deep_think, user_text)
                    if _dt_answer == "__FALLBACK__":
                        pass  # deep model resting; fall through to fast model below
                    else:
                        _broadcast_avatar_state("speaking")
                        await self.session.say("Let me think about that properly, sir.",
                                               allow_interruptions=True)
                        _broadcast_avatar_state("speaking")
                        await self.session.say(_dt_answer, allow_interruptions=True)
                        return
                # 4. avatar fast path: bypass 0.5B tool-call unreliability
                _av_desc = None
                for _pat in ("turn into ", "change your avatar to ",
                             "you should look like ", "look like ",
                             "make yourself look like ",
                             "change your look to ",
                             "i want you to look like "):
                    if _pat in low:
                        _av_desc = low.split(_pat, 1)[1].strip(" .!?").strip()
                        break
                if _av_desc:
                    _broadcast_avatar_state("speaking")
                    await self.session.say(
                        "Give me a few minutes, sir. Painting the new portrait now.",
                        allow_interruptions=True)
                    try:
                        await asyncio.to_thread(
                            _save_identity, None, _av_desc[:300])
                        import subprocess as _sp2
                        _sp2.Popen(
                            [sys.executable,
                             str(VAGAR_HOME / "avatar_gen.py"),
                             _av_desc[:300]],
                            stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL)
                    except Exception:
                        pass
                    return
        except Exception:
            pass  # fall through to normal LLM handling
        await super().on_user_turn_completed(turn_ctx, new_message)

    @function_tool(
        name="run_diagnostic",
        description=(
            "Run a self-diagnostic on Vagar's local services: worker, LiveKit server, "
            "Ollama, avatar server, token server. Use when the user asks for a "
            "diagnostic, health check, or system status."
        ),
    )
    async def run_diagnostic(self) -> str:
        _broadcast_activity("Running full diagnostic\u2026")
        import socket as _so, urllib.request as _ur, time as _t
        def _tcp(h, p, to=5):
            try:
                s = _so.create_connection((h, p), timeout=to); s.close(); return True
            except Exception:
                return False
        def _http(u, to=10):
            try:
                with _ur.urlopen(u, timeout=to) as r:
                    return 200 <= r.status < 400
            except Exception:
                return False
        res = []
        res.append(("LiveKit server", _tcp("127.0.0.1", 7880)))
        res.append(("Ollama brain", _http("http://localhost:11434/api/tags")))
        try:
            age = _t.time() - float(open(
                str(HEARTBEAT_PATH),
                encoding="utf-8").read().strip().split()[0])
            res.append(("Worker heartbeat", age < 180))
        except Exception:
            res.append(("Worker heartbeat", False))
        res.append(("Avatar server", _http("http://localhost:8099/avatar.png")))
        res.append(("Token server", _tcp("127.0.0.1", 7999)))
        bad = [n for n, ok in res if not ok]
        if not bad:
            return ("All systems nominal, sir. Worker, LiveKit, Ollama, "
                    "avatar and token servers all healthy.")
        return ("Diagnostic complete, sir. Issues found: %s. "
                "The watchdog will attempt repairs automatically." % ", ".join(bad))

    @function_tool(
        name="check_tailnet",
        description=(
            "Check the user's Tailscale network for unknown devices. "
            "Use when he asks about network security or unknown devices."
        ),
    )
    async def check_tailnet(self) -> str:
        _broadcast_activity("Scanning tailnet for unknown devices\u2026")
        try:
            import sys as _ts
            _ts.path.insert(0, str(VAGAR_HOME))
            import tailnet_monitor as _tm
            ok, msg, _u = _tm.check()
            return ("Tailnet check, sir: " + msg) if ok else (
                "Security alert, sir: " + msg)
        except Exception as e:
            return f"Tailnet check failed: {e}"

    @function_tool(
        name="security_audit",
        description=(
            "Run a defensive security audit on the user's laptop: firewall, "
            "open ports, RDP, Defender, admin shares. Read-only. Use when he "
            "asks for a security check or hardening review."
        ),
    )
    async def security_audit(self) -> str:
        _broadcast_activity("Running security audit\u2026")
        try:
            import sys as _hs
            _hs.path.insert(0, str(VAGAR_HOME))
            import harden_audit as _ha
            results = await __import__("asyncio").to_thread(_ha.audit)
            return "Security audit, sir:\n" + _ha.format_report(results)
        except Exception as e:
            return f"Audit failed: {e}"

    @function_tool(
        name="ask_specialist",
        description=(
            "Ask one of the user's specialist agents for expert help. "
            "specialist: 'marketing' (titles, descriptions, launch copy), "
            "'sales' (pricing, KDP royalty math), 'kdp' (manuscript/cover "
            "production, publishing pipeline), 'security' (defensive audits, "
            "hardening, threat review). question: the specific question or "
            "task. Use when the user asks about pricing, book production, "
            "marketing copy, or security beyond a quick check."
        ),
    )
    async def ask_specialist(self, specialist: str, question: str) -> str:
        _broadcast_activity(f"Consulting {specialist} specialist\u2026")
        try:
            import sys as _sp, asyncio as _aio
            _sp.path.insert(0, str(VAGAR_HOME))
            import agent_router as _router
            # validate name before the blocking call
            _valid = [n for n, _ in _router.list_agents()]
            _s = specialist.strip().lower()
            if _s not in _valid:
                return (f"No specialist named '{specialist}', sir. "
                        f"Available: {', '.join(_valid)}.")
            # blocking Ollama call -> thread so the voice loop stays alive
            answer = await _aio.to_thread(_router.run, _s, question)
            return f"{_s.capitalize()} specialist, sir:\n{answer}"
        except Exception as e:
            return f"Specialist unavailable: {e}"

    @function_tool(
        name="complete_quest",
        description=(
            "Mark one of the user's active quests as complete and award XP. "
            "quest_name: name of the quest (e.g. 'The Wake Word', "
            "'The Proving Ground'). Use when the user says they finished a quest. "
            "XP is awarded automatically and level-ups are announced."
        ),
    )
    async def complete_quest(self, quest_name: str) -> str:
        _broadcast_activity(f"Completing quest\u2026")
        try:
            import sys as _qs, asyncio as _aio
            _qs.path.insert(0, str(VAGAR_HOME))
            import quest_manager as _qm

            def _do():
                _data = _qm._load()
                _qn = quest_name.strip().lower()
                for _q in _data.get("active_quests", []):
                    if _q["name"].strip().lower() == _qn or _qn in _q["name"].strip().lower():
                        _xp = int(_q.get("xp", 0))
                        _qm.complete_quest(_q["name"], _xp)
                        return _q["name"], _xp
                return None, 0

            _name, _xp = await _aio.to_thread(_do)
            if not _name:
                _active = ", ".join(
                    q["name"] for q in
                    __import__("json").load(open(
                        str(QUESTS_PATH),
                        encoding="utf-8")).get("active_quests", []))
                _broadcast_avatar_state("speaking")
                return (f"I don't see a quest called '{quest_name}', sir. "
                        f"Active quests: {_active}.")
            _broadcast_avatar_state("speaking")
            # check for level up
            _st = _qm.status_text()
            return (f"Quest complete, sir! {_name} done, {_xp} XP awarded. "
                    f"{_st}")
        except Exception as e:
            return f"Could not complete quest: {e}"

    @function_tool(
        name="set_volume",
        description=(
            "Set the laptop system volume (0-100) or mute/unmute. "
            "Use when the user asks to turn volume up/down, mute, or unmute."
        ),
    )
    async def set_volume(self, level: str) -> str:
        """level: 0-100 number, or 'mute'/'unmute'."""
        import subprocess as _sp, os as _os
        _mute_file = str(MUTE_STATE_PATH)
        def _is_muted():
            try:
                return open(_mute_file, encoding="utf-8").read().strip() == "1"
            except Exception:
                return False
        def _set_muted(v: bool):
            try:
                open(_mute_file, "w", encoding="utf-8").write("1" if v else "0")
            except Exception:
                pass
        def _toggle():
            _sp.run(["powershell", "-noprofile", "-c",
                     "(New-Object -ComObject WScript.Shell).SendKeys([char]173)"],
                    timeout=10, capture_output=True)
        try:
            lv = level.strip().lower()
            if lv == "mute":
                if not _is_muted():
                    _toggle()
                    _set_muted(True)
                return "Muted, sir."
            if lv == "unmute":
                if _is_muted():
                    _toggle()
                    _set_muted(False)
                return "Unmuted, sir."
            n = max(0, min(100, int(lv)))
            # Any explicit level clears a tracked mute.
            _set_muted(False)
            _up = int(n / 2)
            _up_cmd = f"1..{_up} | % {{ $o.SendKeys([char]175) }}; " if _up > 0 else ""
            _sp.run(["powershell", "-noprofile", "-c",
                     f"$o = New-Object -ComObject WScript.Shell; "
                     f"1..50 | % {{ $o.SendKeys([char]174) }}; "
                     f"{_up_cmd}"],
                    timeout=15, capture_output=True)
            return f"Volume set to {n}, sir."
        except Exception as e:
            return f"Couldn't change volume: {e}"

    @function_tool(
        name="mark_reminder_done",
        description=(
            "Mark a standing open-loop reminder as done so it stops appearing "
            "in the morning briefing. ids: ambetter, amazon, kdp-cover, wakeword. "
            "Use when the user confirms they completed one of these tasks."
        ),
    )
    async def mark_reminder_done(self, reminder_id: str) -> str:
        import json as _js
        _p = str(STANDING_REMINDERS_PATH)
        try:
            data = _js.load(open(_p, encoding="utf-8"))
            for r in data:
                if r.get("id") == reminder_id:
                    r["done"] = True
                    _js.dump(data, open(_p, "w", encoding="utf-8"), indent=2)
                    return f"Marked '{reminder_id}' done, sir. It won't come up again."
            return f"No standing reminder with id '{reminder_id}'."
        except Exception as e:
            return f"Couldn't update reminders: {e}"

    @function_tool(
        name="get_local_time",
        description=(
            "Get the current local date and time on the user's laptop. "
            "Use it whenever the user asks what time it is or what day it is."
        ),
    )
    async def get_local_time(self) -> str:
        t0 = time.perf_counter()
        ok = True
        try:
            return datetime.now().strftime("%A, %B %d, %Y at %I:%M %p")
        except Exception as e:
            ok = False
            return "Could not read local time: %s" % e
        finally:
            recorder.record(
                "tool_call",
                name="get_local_time",
                args_json="{}",
                latency_ms=round((time.perf_counter() - t0) * 1000, 1),
                ok=ok,
            )

    @function_tool(
        name="enroll_voice",
        description=(
            "Enroll the caller's voiceprint from live call audio. Use when the "
            "user says 'enroll my voice', 'remember my voice', or 'learn my voice'."
        ),
    )
    async def enroll_voice(self) -> str:
        _broadcast_activity("Enrolling voice\u2026")
        global _room_ref
        if _room_ref is None:
            return "I don't have call audio access right now, sir."
        try:
            import sys as _s
            _s.path.insert(0, str(VAGAR_HOME))
            import speaker_id as _spk
        except Exception as e:
            return "Voice module unavailable: %s" % str(e)[:60]
        clips = []
        prompts = [
            "Let's set up your voiceprint, sir. Please speak naturally for about ten seconds. Tell me about your day. Starting now.",
            "Good. Second sample — keep talking for another ten seconds. What are you working on lately?",
            "Last one, sir. Ten more seconds of natural speech. Anything on your mind.",
        ]
        for i, prompt in enumerate(prompts):
            await self.session.say(prompt, allow_interruptions=False)
            cap = await capture_speech(min_speech_s=6.0, timeout_s=22.0)
            if cap is None:
                await self.session.say(
                    "I didn't catch enough speech that time, sir. Enrollment cancelled — say 'enroll my voice' to try again.",
                    allow_interruptions=True)
                return "Enrollment cancelled: insufficient speech."
            clips.append(cap)
        try:
            res = await __import__("asyncio").to_thread(
                _spk.enroll_from_pcm, USER_NAME.lower(), clips)
        except Exception as e:
            return "Enrollment failed: %s" % str(e)[:80]
        try:
            recorder.record("voice_enrolled", name=USER_NAME.lower(),
                            threshold=res.get("threshold"),
                            genuine_sims=res.get("genuine_sims"))
        except Exception:
            pass
        await self.session.say(
            "Voiceprint enrolled, sir. I'll know your voice from now on.",
            allow_interruptions=True)
        return "Enrolled %s: %s" % (USER_NAME, str(res))

    @function_tool(
        name="identify_speaker",
        description=(
            "Check who is currently speaking on the call using their enrolled "
            "voiceprint. Use it when the user asks who is speaking or whether "
            "you recognize their voice."
        ),
        )
    async def identify_speaker(self) -> str:
        _broadcast_activity("Identifying speaker\u2026")
        st = speaker_state.get("status", "pending")
        if st == "verified":
            return ("Yes, sir. Your voice matches the enrolled profile for %s."
                    % speaker_state.get("name", "you"))
        if st == "unknown":
            return "I do not recognize this voice, sir."
        if st == "no_profile":
            return "No voice has been enrolled yet, sir."
        if st == "pending":
            return "Still listening for a clear voice sample, sir."
        return "Voice check hit a snag, sir."

    @function_tool(
        name="look",
        description=(
            "See through the caller's phone camera. Captures the latest video "
            "frame and describes it with the on-device vision model. Use when the "
            "user asks what you can see, what something looks like, or to read "
            "text visible on camera. Pass a specific question to focus the "
            "description (e.g. 'what does this label say?')."
        ),
    )
    async def look(self, question: str = "Describe what you see in one or two sentences.") -> str:
        _broadcast_activity("Looking at camera\u2026")
        t0 = time.perf_counter()
        ok = True
        try:
            return await describe_camera_frame(question)
        except Exception as e:
            ok = False
            return "Vision failed: %s: %s" % (type(e).__name__, e)
        finally:
            recorder.record(
                "tool_call",
                name="look",
                args_json=json.dumps({"question": question[:80]}),
                latency_ms=round((time.perf_counter() - t0) * 1000, 1),
                ok=ok,
            )

    # --- self-evolving skills (local, free) ---
    @function_tool(
        name="create_skill",
        description=(
            "Create a new skill for Vagar from a plain-language description. The "
            "on-device model drafts the skill code, it is validated in a sandbox, "
            "and staged for review. The skill does NOT become active until the user "
            "explicitly approves it. Use this when the user asks Vagar to learn a new "
            "ability. Args: name (short snake_case name, e.g. 'roll_dice'), spec "
            "(what the skill should do)."
        ),
    )
    async def create_skill(self, name: str, spec: str) -> str:
        _broadcast_activity("Drafting new skill\u2026")
        _broadcast_activity("Drafting new skill\u2026")
        t0 = time.perf_counter()
        ok = True
        clean = "?"
        try:
            clean = sanitize_name(name)
            if not re.match(r"^[a-z][a-z0-9_]{1,40}$", clean):
                return "That skill name is not valid. Use a short snake_case name like 'roll_dice'."
            if os.path.isfile(os.path.join(SKILLS_DIR, clean + ".py")):
                return "A skill named '%s' already exists." % clean
            code = await asyncio.to_thread(draft_skill_code, clean, spec)
            valid, msg = await asyncio.to_thread(validate_skill_code, clean, code)
            stage_skill(clean, code)
            if valid:
                return (
                    "Drafted skill '%s' and it passed validation (%s). It is STAGED, "
                    "not active yet. Describe what it does and ask the user to say "
                    "'approve skill %s' to activate it." % (clean, msg, clean)
                )
            return (
                "Drafted skill '%s' but validation failed: %s. It is staged anyway "
                "so it can be inspected; the user can ask for a revision." % (clean, msg)
            )
        except Exception as e:
            ok = False
            return "create_skill failed: %s: %s" % (type(e).__name__, e)
        finally:
            recorder.record(
                "tool_call",
                name="create_skill",
                args_json=json.dumps({"name": clean}),
                latency_ms=round((time.perf_counter() - t0) * 1000, 1),
                ok=ok,
            )

    @function_tool(
        name="list_pending_skills",
        description="List skill drafts that are staged and waiting for the user's approval.",
    )
    async def list_pending_skills(self) -> str:
        _broadcast_activity("Listing pending skills\u2026")
        pending = list_staged_skills()
        if not pending:
            return "No skills are waiting for approval."
        return "Skills awaiting approval: " + ", ".join(pending)

    @function_tool(
        name="list_skills",
        description="List the skills currently active on Vagar.",
    )
    async def list_skills(self) -> str:
        live = list_live_skills()
        base = ["get_local_time", "look", "create_skill", "list_pending_skills",
                "approve_skill", "reject_skill", "list_skills"]
        return "Active skills: " + ", ".join(base + live)

    @function_tool(
        name="approve_skill",
        description=(
            "Approve a staged skill, making it live for the next call. ONLY the user "
            "may approve skills - never call this on your own initiative. Only call "
            "it when the user explicitly asks to approve a skill, naming it."
        ),
    )
    async def approve_skill(self, name: str) -> str:
        _broadcast_activity("Reviewing skill\u2026")
        t0 = time.perf_counter()
        ok = True
        clean = sanitize_name(name)
        try:
            dst = await asyncio.to_thread(approve_skill_file, clean)
            return ("Skill '%s' is now live. It will be available from the next call "
                    "onward." % clean)
        except FileNotFoundError:
            ok = False
            return "There is no staged skill named '%s'." % clean
        except Exception as e:
            ok = False
            return "approve_skill failed: %s: %s" % (type(e).__name__, e)
        finally:
            recorder.record(
                "tool_call",
                name="approve_skill",
                args_json=json.dumps({"name": clean}),
                latency_ms=round((time.perf_counter() - t0) * 1000, 1),
                ok=ok,
            )

    @function_tool(
        name="reject_skill",
        description=(
            "Discard a staged skill draft without activating it. Use when the user "
            "declines a drafted skill."
        ),
    )
    async def reject_skill(self, name: str) -> str:
        _broadcast_activity("Rejecting skill\u2026")
        clean = sanitize_name(name)
        try:
            await asyncio.to_thread(reject_skill_file, clean)
            return "Staged skill '%s' has been discarded." % clean
        except FileNotFoundError:
            return "There is no staged skill named '%s'." % clean
        except Exception as e:
            return "reject_skill failed: %s: %s" % (type(e).__name__, e)
    @function_tool(
        name="note_skill_gap",
        description=(
            "Log something the user asked for that the assistant cannot do with any "
            "current tool, or a tool that keeps failing at. Call this when you have "
            "to say 'I can't do that' so a skill can be suggested for it later. "
            "Args: description (short plain-language summary, e.g. 'read text "
            "from PDF files')."
        ),
    )
    async def note_skill_gap(self, description: str) -> str:
        try:
            entry = await asyncio.to_thread(skill_curiosity.log_gap, description)
            n = int(entry.get("count", 1))
            return ("Noted. If this keeps coming up I'll suggest learning a skill "
                    "for it. (Seen %d time%s.)" % (n, "" if n == 1 else "s"))
        except Exception as e:
            return "Could not log that: %s" % e

    @function_tool(
        name="dismiss_skill_gap",
        description=(
            "Snooze a logged or suggested skill gap when the user isn't interested "
            "(e.g. 'never mind', 'don't bother', 'not now'). It stays logged but "
            "won't be suggested again. Args: description (which gap)."
        ),
    )
    async def dismiss_skill_gap(self, description: str) -> str:
        try:
            ok = await asyncio.to_thread(skill_curiosity.snooze_gap, description)
            return ("Dropped it - I won't bring that one up again."
                    if ok else "I don't have that gap logged.")
        except Exception as e:
            return "Could not dismiss that: %s" % e

    @function_tool(
        name="list_skill_gaps",
        description="List the capability gaps logged as candidates for new skills.",
    )
    async def list_skill_gaps(self) -> str:
        try:
            gaps = await asyncio.to_thread(skill_curiosity.list_gaps)
            if not gaps:
                return "Nothing logged - I haven't hit anything I can't do lately."
            return "Gaps I've logged: " + "; ".join(
                "%s (seen %d)" % (g.get("description", "?")[:60], int(g.get("count", 0)))
                for g in gaps[:8])
        except Exception as e:
            return "Could not list gaps: %s" % e

    @function_tool(
        name="lookup_skill",
        description=(
            "Look up how to build a skill on the web, then draft it through the "
            "normal sandboxed pipeline. Fetched pages are prompt-injection scanned; "
            "the draft is compile-checked and STAGED, never auto-activated - the "
            "user must approve it with approve_skill. Use when the user asks to "
            "learn something and wants web research first ('look up a skill for X'). "
            "Args: query (what the skill should do), name (optional short "
            "snake_case name)."
        ),
    )
    async def lookup_skill(self, query: str, name: str = "") -> str:
        _broadcast_activity("Looking up skill designs\u2026")
        t0 = time.perf_counter()
        ok = True
        try:
            res = await skill_lookup.lookup_and_draft(query, name)
            if not res.get("ok"):
                ok = False
            return res.get("message", "Lookup finished.")
        except Exception as e:
            ok = False
            return "lookup_skill failed: %s: %s" % (type(e).__name__, e)
        finally:
            recorder.record(
                "tool_call",
                name="lookup_skill",
                args_json=json.dumps({"query": str(query)[:60]}),
                latency_ms=round((time.perf_counter() - t0) * 1000, 1),
                ok=ok,
            )

    @function_tool(
        name="change_name",
        description=(
            "Change Vagar's name. Use when the user says 'change your name to X', "
            "'call yourself X', or 'your new name is X'. The new name takes effect "
            "on the next call."
        ),
    )
    async def change_name(self, name: str) -> str:
        t0 = time.perf_counter()
        ok = True
        try:
            clean = str(name).strip()
            if not clean or len(clean) > 40:
                ok = False
                return "That name won't do, sir. Keep it short - one or two words."
            for prefix in ("call yourself ", "your name is ", "name yourself "):
                if clean.lower().startswith(prefix):
                    clean = clean[len(prefix):].strip()
            clean = clean.strip('"').strip("'").strip()
            if not clean:
                ok = False
                return "I didn't catch the new name, sir."
            await asyncio.to_thread(_save_identity, clean, None)
            return "Very good, sir. I shall be %s from our next call onward." % clean
        except Exception as e:
            ok = False
            return "Name change failed: %s: %s" % (type(e).__name__, e)
        finally:
            recorder.record(
                "tool_call",
                name="change_name",
                args_json=json.dumps({"name": str(name)[:40]}),
                latency_ms=round((time.perf_counter() - t0) * 1000, 1),
                ok=ok,
            )

    @function_tool(
        name="change_avatar",
        description=(
            "Change Vagar's avatar portrait. Use when the user says 'change your look', "
            "'turn into X', 'you should look like X', or describes a new appearance. "
            "Generates a new portrait locally in the background (takes several minutes); "
            "the phone app shows it on the next call. Arg: description (what Vagar should look like)."
        ),
    )
    async def change_avatar(self, description: str) -> str:
        _broadcast_activity("Changing avatar\u2026")
        t0 = time.perf_counter()
        ok = True
        try:
            desc = str(description).strip()
            if not desc:
                ok = False
                return "Describe the look you'd like, sir."
            if len(desc) > 300:
                desc = desc[:300]
            await asyncio.to_thread(_save_identity, None, desc)
            import subprocess as _sp
            _sp.Popen(
                [sys.executable, str(VAGAR_HOME / "avatar_gen.py"), desc],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
            return ("Give me a few minutes, sir. I'm painting the new portrait now - "
                    "you'll see it in the app on our next call.")
        except Exception as e:
            ok = False
            return "Avatar change failed: %s: %s" % (type(e).__name__, e)
        finally:
            recorder.record(
                "tool_call",
                name="change_avatar",
                args_json=json.dumps({"description": str(description)[:80]}),
                latency_ms=round((time.perf_counter() - t0) * 1000, 1),
                ok=ok,
            )
    # --- end identity tools ---

    # --- end self-evolving skills ---


# --- prewarmed models: loaded once at worker start, shared by every session ---
_vad_instance = None
_stt_instance = None
_tts_instance = None


def get_vad():
    global _vad_instance
    if _vad_instance is None:
        _vad_instance = silero.VAD.load()
    return _vad_instance


def get_stt():
    global _stt_instance
    if _stt_instance is None:
        _stt_instance = FasterWhisperSTT()
    return _stt_instance


def get_tts():
    global _tts_instance
    if _tts_instance is None:
        _tts_instance = KokoroTTS()
    return _tts_instance


def prewarm(proc):
    """Worker startup hook: load whisper (~150MB) and the Kokoro voice into RAM
    now, so the first call answers in ~2s instead of ~20s."""
    # --- self-healing heartbeat: vagar_watchdog.py restarts us if this goes stale ---
    import threading as _th, time as _tt
    def _vagar_hb():
        _p = str(HEARTBEAT_PATH)
        while True:
            try:
                with open(_p, "w") as _f:
                    _f.write(str(_tt.time()))
            except Exception:
                pass
            _tt.sleep(60)
    _th.Thread(target=_vagar_hb, daemon=True).start()
    # Prewarm the vision model so first "what do you see" isn't 51s cold
    try:
        import urllib.request as _ur, json as _js
        _pl = {"model": "moondream", "prompt": "ok", "stream": False}
        _rq = _ur.Request("http://localhost:11434/api/generate",
                         data=_js.dumps(_pl).encode(),
                         headers={"Content-Type": "application/json"}, method="POST")
        _ur.urlopen(_rq, timeout=120)
    except Exception:
        pass
    # Jarvis vision: YOLO real-time object detection on camera frames
    # Two eyes: phone camera (primary) + laptop webcam (fallback)
    try:
        import sys as _sy
        _sy.path.insert(0, str(VAGAR_HOME))
        import yolo_watch as _yw
        _yw.start(frame_bucket, name="phone", interval=1.0)
        try:
            import laptop_cam as _lc
            _lc.start()
            _yw.start(_lc.laptop_frame_bucket, name="laptop", interval=2.0)
        except Exception:
            pass
    except Exception:
        pass
    # Self-healing layer 2: supervise watcher threads, no worker restart needed
    try:
        import self_heal as _shp
        _shp.start_supervisor()
    except Exception:
        pass
    get_vad()
    get_stt()
    get_tts()
    try:
        recorder.record("prewarm", note="whisper+piper loaded at worker start")
    except Exception:
        pass


# --- end prewarmed models ---


def _make_ollama_client():
    """Ollama client with 120s timeout (i3 CPU needs >10s for large prompts)."""
    return OpenAIAsyncClient(
        base_url=OLLAMA_URL,
        api_key="ollama-local",
        timeout=httpx.Timeout(120.0),
        http_client=httpx.AsyncClient(timeout=httpx.Timeout(120.0)),
    )


# --- proactive battery warnings (owner-approved 2026-10-06) ---
# Background poll, active ONLY during calls. Speaks latched once-per-level
# warnings at 30% and 15% via session.say. Daemon thread; every failure
# mode is swallowed so it can never crash the agent or spam speech.
def _say_from_thread(loop, session, text):
    try:
        fut = asyncio.run_coroutine_threadsafe(
            session.say(text, allow_interruptions=True), loop)
        fut.result(timeout=180)
    except Exception:
        pass


def _battery_watch_loop(stop_event, loop, session,
                        first_delay=60, interval=300):
    try:
        import sys as _bws
        from pathlib import Path as _bwp
        _bws.path.insert(0, str(_bwp(__file__).resolve().parent / "skills"))
        from battery_monitor import check_battery as _check_batt
    except Exception:
        return
    warned = {"low": False, "critical": False}
    try:
        if stop_event.wait(first_delay):  # let greeting/briefing finish
            return
        while not stop_event.is_set():
            try:
                st = _check_batt()
                if st.get("available") and not st.get("plugged_in"):
                    lvl, pct = st.get("level"), st.get("percent")
                    if lvl == "critical" and not warned["critical"]:
                        warned["critical"] = warned["low"] = True
                        _say_from_thread(
                            loop, session,
                            "Sir, the laptop battery is critical at %s percent. "
                            "Please plug in the charger, or I may go dark "
                            "mid-sentence." % pct)
                    elif lvl == "low" and not warned["low"]:
                        warned["low"] = True
                        _say_from_thread(
                            loop, session,
                            "Sir, a gentle reminder \u2014 the laptop battery is at "
                            "%s percent and not charging. You may want to plug "
                            "in soon." % pct)
                else:
                    # plugged in or recovered: re-arm both latches
                    warned["low"] = warned["critical"] = False
            except Exception:
                pass
            stop_event.wait(interval)
    except Exception:
        pass


async def entrypoint(ctx: JobContext):
    await ctx.connect()

    session_id = recorder.start_session()
    global _room_ref
    _room_ref = ctx.room
    watch_room_video(ctx.room)
    start_speaker_check(ctx.room)

    session = AgentSession(
        vad=get_vad(),
        stt=get_stt(),
        llm=openai.LLM.with_ollama(
            model=OLLAMA_MODEL,
            base_url=OLLAMA_URL,
            client=_make_ollama_client(),
        ),
        tts=get_tts(),
        # Local VAD turn detection. The default tries LiveKit Cloud's
        # adaptive model, which 401s against the local server and phones
        # home -- local-first means it stays off.
        turn_detection="vad",
    )

    # --- flight recorder: session event hooks (livekit-agents 1.8.3) ---
    # user_input_transcribed -> session-confirmed transcript (whisper-level
    # latency is recorded separately in FasterWhisperSTT as source="whisper").
    # conversation_item_added -> llm_response for assistant turns, with an
    # approximate turn latency measured from the last final transcript.
    # NOTE: 1.8.3 emits no "error" event on the session, so errors are
    # captured with a try/except around the session body instead.
    # NOTE: tool_call is recorded inside the tool itself (with latency),
    # not from the "function_tools_executed" event, to avoid double logging.
    _last_final_transcript_ts = 0.0
    _exchanges = []  # for session continuity snapshot

    def _on_user_input_transcribed(ev):
        nonlocal _last_final_transcript_ts, _exchanges
        try:
            if ev.is_final:
                _last_final_transcript_ts = time.time()
                _exchanges.append({"role": "user", "text": ev.transcript})
                recorder.record("stt_result", text=ev.transcript, source="session")
        except Exception:
            pass

    def _on_conversation_item_added(ev):
        try:
            item = ev.item
            if getattr(item, "role", None) == "assistant":
                text = getattr(item, "text_content", None) or ""
                lat = (
                    (time.time() - _last_final_transcript_ts) * 1000
                    if _last_final_transcript_ts
                    else None
                )
                recorder.record(
                    "llm_response",
                    model=OLLAMA_MODEL,
                    output_chars=len(text),
                    latency_ms=round(lat, 1) if lat is not None else None,
                    latency_note="final-transcript to assistant item (approx turn latency)",
                    text=text,
                )
                _exchanges.append({"role": "assistant", "text": text})
        except Exception:
            pass

    session.on("user_input_transcribed", _on_user_input_transcribed)
    session.on("conversation_item_added", _on_conversation_item_added)
    # --- end flight recorder hooks ---

    # --- avatar state broadcast: drive the phone's animated avatar ---
    # agent_state_changed: idle/listening/thinking/speaking -> same avatar state
    # tool_execution_updated: any tool running -> "working" (laptop is busy)
    def _on_agent_state_changed(ev):
        try:
            st = getattr(ev, "new_state", None) or ""
            if st == "initializing":
                st = "idle"
            if st in ("idle", "listening", "thinking", "speaking"):
                _broadcast_avatar_state(st)
        except Exception:
            pass

    def _on_tool_execution_updated(ev):
        try:
            # tool_execution_updated fires on start and finish. Show
            # "working" only while a tool is running; on finish fall back
            # to idle so the avatar doesn't freeze on the working loop.
            _finished = False
            try:
                _finished = bool(getattr(ev, "is_finished", False) or
                                 getattr(getattr(ev, "execution", None), "is_finished", False))
            except Exception:
                pass
            if _finished:
                global _avatar_state_last
                # force-clear: bypass dedup so idle always broadcasts
                _avatar_state_last = ""
                _broadcast_avatar_state("idle")
            else:
                _broadcast_avatar_state("working")
        except Exception:
            pass

    session.on("agent_state_changed", _on_agent_state_changed)
    session.on("tool_execution_updated", _on_tool_execution_updated)
    # --- end avatar state broadcast ---

    try:
        await session.start(
            agent=VagarAgent(
                instructions=_build_instructions(),
                tools=load_skill_tools(),  # approved local skills, fresh every session
            ),
            room=ctx.room,
        )
        # --- proactive battery warnings: background poll, this call only ---
        # owner-approved 2026-10-06. Daemon thread; stopped in finally.
        _battery_stop = threading.Event()
        _battery_thread = threading.Thread(
            target=_battery_watch_loop,
            args=(_battery_stop, asyncio.get_running_loop(), session),
            daemon=True, name="vagar-battery-watch")
        _battery_thread.start()
        _nm = _load_identity()["name"]
        await session.say(__import__("random").choice([
            "Good day, " + USER_FORMAL_NAME + ". %s at your service. Ask me what I can do, for the full list." % _nm,
            "Welcome back, sir. Your valet is at your disposal. Ask me what I can do, for the full list.",
            "A pleasure to hear from you, " + USER_FORMAL_NAME + ". How may I assist? Ask me what I can do, for the full list.",
            "At your service, sir. %s here, ready when you are. Ask me what I can do, for the full list." % _nm,
        ]))
        # --- morning briefing: once per day, first session ---
        # Ask-first: one short offer, full briefing only on yes.
        global _briefing_offered
        _briefing_offered = False
        if _should_brief():
            _briefing_offered = True
            await session.say("Morning, sir. Want the briefing?",
                              allow_interruptions=True)
            _mark_briefed()
        # --- quest announcements: congratulate on completed quests ---
        try:
            import sys as _sys
            _sys.path.insert(0, str(VAGAR_HOME))
            import quest_manager as _qm
            _ann = await asyncio.to_thread(_qm.pop_announcements)
            for _a in _ann:
                await session.say(_a, allow_interruptions=True)
        except Exception:
            pass
        # --- healer escalation: speak a pending self-heal alert once ---
        # Staged by evolving_healer when every recovery strategy has failed.
        try:
            import self_heal as _shesc
            _esc = _shesc.pop_pending_escalation()
            if _esc:
                await session.say(_esc, allow_interruptions=True)
        except Exception:
            pass
        # --- skill curiosity: surface at most one top gap suggestion ---
        # Ask-first, once per day per gap. A yes leads to create_skill;
        # a no/dismiss leads to dismiss_skill_gap. Never auto-drafts.
        try:
            _gap = await asyncio.to_thread(skill_curiosity.get_top_gap)
            if _gap and await asyncio.to_thread(skill_curiosity.should_suggest, _gap):
                await asyncio.to_thread(skill_curiosity.mark_suggested, _gap["key"])
                await session.say(
                    "I keep running into '%s' with no good tool for it. "
                    "Shall I learn a skill for that?" % str(_gap.get("description", ""))[:90],
                    allow_interruptions=True)
        except Exception:
            pass
        # Stay on the call until the user hangs up. Without this the
        # entrypoint returns right after the greeting, the job ends, and
        # the agent leaves the room (no STT, no tools, no vision).
        _disconnected = asyncio.Event()
        ctx.room.on("disconnected", lambda: _disconnected.set())
        await _disconnected.wait()
    except Exception as e:
        recorder.record("error", where="entrypoint", message="%s: %s" % (type(e).__name__, e))
        raise
    finally:
        try:
            _battery_stop.set()  # stop the proactive battery watch
        except Exception:
            pass
        try:
            _save_session_snapshot(_exchanges)
        except Exception:
            pass
        recorder.end_session()


if __name__ == "__main__":
    cli.run_app(WorkerOptions(entrypoint_fnc=entrypoint, prewarm_fnc=prewarm, num_idle_processes=1))


