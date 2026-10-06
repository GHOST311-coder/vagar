# Vagar

**Vagar** is a local-first voice AI assistant — your own Jarvis, running entirely on your machine. No cloud, no subscription, no data leaving your network.

Talk to it over LiveKit (phone app or browser), and it answers with a natural voice, remembers facts across sessions, runs local skills, tracks D&D-style quests with XP, and can even draft new skills for itself.

## Features

- **Real-time voice loop** — faster-whisper speech-to-text, Ollama LLM brain, Kokoro neural TTS, Silero voice activity detection. All local, all offline-capable.
- **Two-tier brain** — fast model (`qwen2.5:0.5b`) for instant replies, deep model (`qwen2.5:3b`) for complex questions. Canned responses answer instantly with zero LLM latency.
- **Skills system** — approved skills live in `skills/` and load fresh every session (no restart needed). Includes: reminders, recurring routines, battery monitor, web fetch (with SSRF guards + prompt-injection scanning), long-term memory, dice roller, system status, batch monitor, local wiki builder.
- **Self-evolving skills** — Vagar can draft new skills from your descriptions, stage them for your approval, and activate them on your word. Nothing self-activates without you.
- **Long-term memory** — facts persist in `vagar_memory.md`, recalled at every session start.
- **Quests & XP** — D&D-framed goals with experience points and level-ups, announced by voice.
- **Alfred-grade manners** — refined, courteous, dry wit. Answers first, no throat-clearing, speaks naturally (no Markdown or code read aloud).
- **Defensive security** — prompt-injection guard on web content, private-network fetch blocking.
- **Flight recorder** — every session traced to local JSONL; replay with `python flightlog.py list|show|tail`. The recorder can never crash the voice loop.
- **Self-healing** — circuit breakers for vision and deep-think models with graceful degradation, a supervisor that restarts stale watcher threads, and an evolving healer that journals recovery attempts and ranks strategies by success rate. It never rewrites code on its own.
- **Vision** — YOLOv8 real-time object detection on phone and laptop-webcam frames ("what do you see?" answered instantly), Moondream fallback for rich descriptions.
- **Speaker verification** — local ECAPA-TDNN voiceprints (embeddings only, never raw audio). Enroll with `python speaker_id.py enroll <name> sample1.wav sample2.wav ...`.
- **Recurring routines** — plain-English repeat schedules ("every weekday at 7am"); due routines are spoken at the start of a call and reschedule themselves.
- **Battery monitor** — proactive low/critical battery warnings.
- **Local wiki** — `skills/wiki_builder.py` generates a single-file offline wiki from the skills, memory, quests, and agent config. Serve on localhost/tailnet only — never expose it publicly.

## Requirements

- **OS:** Windows 10/11 (primary), Linux/macOS should work with minor path tweaks
- **Python:** 3.10+
- **Ollama** running locally ([ollama.com](https://ollama.com)) with:
  - `qwen2.5:0.5b` (fast brain) — `ollama pull qwen2.5:0.5b`
  - `qwen2.5:3b` (deep brain) — `ollama pull qwen2.5:3b`
  - `moondream` (vision, optional) — `ollama pull moondream`
- **LiveKit server** ([livekit.io](https://livekit.io)) for real-time voice
- **Kokoro voice model** — ONNX files go in `voices/kokoro/` (see Configuration)

## Setup

```powershell
# 1. Clone
git clone https://github.com/YOUR-USERNAME/vagar.git
cd vagar

# 2. Python environment (use the real interpreter, not venv launchers, on locked-down systems)
C:\Python310\python.exe -m pip install -r requirements.txt

# 3. Personalize (optional but recommended)
copy .env.example .env
notepad .env   # set VAGAR_USER_NAME, VAGAR_USER_BIO, model paths

# 4. Voice model files
# Place Kokoro ONNX model + voices in voices/kokoro/, or set
# VAGAR_KOKORO_MODEL / VAGAR_KOKORO_VOICES in .env

# 5. Start Ollama models
ollama pull qwen2.5:0.5b
ollama pull qwen2.5:3b

# 6. Start the LiveKit server (separate terminal), then run Vagar
C:\Python310\python.exe agent.py
```

Vagar registers as a LiveKit worker and waits for you to join its room. Runtime data (memory, quests, reminders) is created automatically in the project directory on first run.

## Configuration

All settings live in `config.py` and resolve from the project directory — no hardcoded paths. Override anything with environment variables or a `.env` file (see `.env.example`):

| Variable | Default | Purpose |
|---|---|---|
| `VAGAR_USER_NAME` | `friend` | Your first name |
| `VAGAR_USER_FORMAL_NAME` | `sir` | Formal address for greetings |
| `VAGAR_USER_BIO` | _(generic)_ | 1–2 sentences about you, used in the system prompt |
| `VAGAR_NAME` | `Vagar` | The assistant's name |
| `VAGAR_DATA_DIR` | _(project root)_ | Where runtime JSON/MD files live |
| `VAGAR_OLLAMA_URL` | `http://localhost:11434/v1` | Ollama OpenAI-compatible endpoint |
| `VAGAR_OLLAMA_MODEL` | `qwen2.5:0.5b` | Fast brain |
| `VAGAR_OLLAMA_DEEP_MODEL` | `qwen2.5:3b` | Deep brain |
| `VAGAR_KOKORO_VOICE` | `bm_lewis` | TTS voice |

## Project structure

```
vagar/
├── agent.py            # Main voice agent (LiveKit worker)
├── config.py           # All paths, user profile, service settings
├── skill_manager.py    # Skill loading + approval workflow
├── quest_manager.py    # XP / level / quest tracking
activity.py          # LiveKit data-channel activity broadcast
flight_recorder.py   # JSONL run tracing (sessions never crash the loop)
flightlog.py         # Offline viewer: list/show/tail recorded sessions
self_heal.py         # Circuit breakers + supervisor for degraded components
yolo_watch.py        # YOLOv8 real-time object inventory (phone + laptop)
laptop_cam.py        # Laptop webcam frame capture
speaker_id.py        # Local speaker verification (ECAPA-TDNN)
├── skills/             # Approved skills (loaded fresh each session)
│   ├── memory.py       # Long-term memory (recall/remember)
│   ├── reminders.py    # One-time reminders
│   ├── web_fetch.py    # Public-page fetch with SSRF guards
│   ├── ops.py          # System/batch status
│   ├── roll_dice.py    # Dice roller (example skill)
battery_monitor.py   # Proactive low-battery warnings
evolving_healer.py   # Journaled, ranked recovery strategies
routines.py          # Recurring routines (plain-English schedules)
wiki_builder.py      # Static offline wiki generator
│   └── staging/        # Draft skills awaiting your approval (never auto-imported)
├── .env.example        # Personalization template
└── requirements.txt
```

## Skills: approve your own

Say *"create a skill that …"* and Vagar drafts the Python, stages it under `skills/staging/`, and shows you the code. Say *"approve <name>"* and it goes live at the next session — no restart. Say *"reject <name>"* to delete it.

Vagar is also curious on its own: when you ask for something no skill can do, it logs the gap and may suggest learning a skill for it (ask-first, once a day at most). Say *"look up a skill for …"* and it researches implementations on the web (pages are prompt-injection scanned), drafts through the same sandboxed pipeline, and stages the result for your approval. Nothing ever activates without your say-so.

## Privacy

Everything runs on your machine. The LLM, STT, and TTS are all local models. The web_fetch skill only makes outbound HTTPS requests to public pages you ask about, with strict blocks on private/loopback/link-local addresses (including redirect targets). No telemetry, no accounts, no cloud.

## License

MIT — see [LICENSE](LICENSE).
