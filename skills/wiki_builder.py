"""Vagar wiki builder: generates a static local wiki from Vagar's own files.

Reads the live skills directory, the memory file, quests.json, and agent.py,
then writes a single self-contained wiki.html (inline CSS, no frameworks,
no CDN, works fully offline).

Serving: this page is for the owner's eyes only. Serve it from the laptop on
localhost or the tailnet only (e.g. the existing avatar static server or
`python -m http.server` bound to 127.0.0.1). Never expose it publicly —
it contains private memory and quest data.

Nothing here activates until the owner approves it.
"""
import html
import json
import os
import re
from datetime import datetime

import sys as _cfg_sys
from pathlib import Path as _cfg_Path
_cfg_sys.path.insert(0, str(_cfg_Path(__file__).resolve().parent.parent))
import config as _cfg
# All source paths come from config.py (project root); nothing hardcoded.
VAGAR_DIR = str(_cfg.VAGAR_HOME)
SKILLS_DIR = str(_cfg.SKILLS_DIR)
MEMORY_PATH = str(_cfg.MEMORY_PATH)
QUESTS_PATH = str(_cfg.QUESTS_PATH)
AGENT_PATH = str(_cfg.VAGAR_HOME / "agent.py")
OUT_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "wiki.html")


def _read(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except OSError:
        return ""


def _esc(s):
    return html.escape(s or "")


def parse_skills():
    """[(filename, docstring, [(tool_name, tool_description), ...]), ...]"""
    skills = []
    try:
        files = sorted(os.listdir(SKILLS_DIR))
    except OSError:
        return skills
    for fn in files:
        if not fn.endswith(".py") or fn.startswith("__"):
            continue
        src = _read(os.path.join(SKILLS_DIR, fn))
        if not src:
            continue
        m = re.match(r'\s*"""(.*?)"""', src, re.DOTALL)
        doc = " ".join(m.group(1).split()) if m else ""
        tools = []
        for tm in re.finditer(
                r"@function_tool\(\s*name\s*=\s*\"([^\"]+)\"\s*,\s*"
                r"description\s*=\s*(\(.*?\))\s*,?\s*\)",
                src, re.DOTALL):
            name = tm.group(1)
            desc = " ".join(re.findall(r"\"((?:[^\"\\]|\\.)*)\"",
                                       tm.group(2))).replace('\\"', '"')
            # fallback for description="..." single-string form
            if not desc:
                sm = re.search(r"description\s*=\s*\"([^\"]+)\"", tm.group(0))
                desc = sm.group(1) if sm else ""
            tools.append((name, " ".join(desc.split())))
        skills.append((fn, doc, tools))
    return skills


def parse_memory():
    text = _read(MEMORY_PATH)
    bullets = [b.strip("- ").strip() for b in text.splitlines()
               if b.strip().startswith("- ")]
    return [b for b in bullets if b]


def parse_quests():
    try:
        with open(QUESTS_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def parse_agent():
    src = _read(AGENT_PATH)
    info = {}
    for key, pat in [
        ("stt_model", r'WHISPER_MODEL\s*=\s*"([^"]+)"'),
        ("tts_voice", r'KOKORO_VOICE\s*=\s*"([^"]+)"'),
        ("fast_model", r'OLLAMA_MODEL\s*=\s*"([^"]+)"'),
        ("vision_model", r'VISION_MODEL\s*=\s*"([^"]+)"'),
        ("deep_model", r'DEEP\w*_MODEL\s*=\s*"([^"]+)"'),
        ("pipeline", r"mic\s*->\s*(.+?)\s*->\s*speaker"),
    ]:
        m = re.search(pat, src)
        info[key] = m.group(1).strip() if m else ""
    return info


def example_phrases(skills):
    """Pull 'quoted' trigger phrases out of tool descriptions."""
    phrases = []
    seen = set()
    for _fn, _doc, tools in skills:
        for name, desc in tools:
            for q in re.findall(r"'([^']{3,60})'", desc):
                if q in seen:
                    continue
                # skip format specs ('YYYY-MM-DD HH:MM') and bare words ('when')
                if re.search(r"YYYY|HH|MM|DD|N minutes", q) or len(q) <= 4:
                    continue
                seen.add(q)
                phrases.append((q, name))
    return phrases


CSS = """
body{font-family:Georgia,serif;max-width:820px;margin:0 auto;padding:24px;
color:#1a1a1a;background:#faf8f2;line-height:1.6}
nav{background:#2b2b2b;padding:12px 18px;border-radius:8px;margin-bottom:28px}
nav a{color:#e8dcc0;margin-right:16px;text-decoration:none;font-size:15px}
nav a:hover{text-decoration:underline}
h1{font-size:32px;border-bottom:3px solid #2b2b2b;padding-bottom:8px}
h2{font-size:24px;margin-top:36px;color:#3a3a3a}
h3{font-size:18px;margin-top:20px}
table{border-collapse:collapse;width:100%;margin:12px 0}
th,td{border:1px solid #ccc;padding:8px 10px;text-align:left;vertical-align:top}
th{background:#2b2b2b;color:#e8dcc0}
tr:nth-child(even){background:#f0ece1}
code{background:#eee8d8;padding:2px 6px;border-radius:4px;font-size:14px}
.pipe{background:#2b2b2b;color:#ffd97a;padding:14px 18px;border-radius:8px;
font-family:monospace;font-size:15px;margin:16px 0}
ul li{margin-bottom:6px}
.meta{color:#777;font-size:13px;margin-top:40px;border-top:1px solid #ccc;padding-top:10px}
"""


def build():
    skills = parse_skills()
    memory = parse_memory()
    quests = parse_quests()
    agent = parse_agent()
    phrases = example_phrases(skills)
    now = datetime.now().strftime("%Y-%m-%d %H:%M")

    parts = []
    parts.append("<!DOCTYPE html><html lang='en'><head><meta charset='utf-8'>")
    parts.append("<meta name='viewport' content='width=device-width,initial-scale=1'>")
    parts.append("<title>Vagar Wiki</title><style>%s</style></head><body>" % CSS)
    parts.append("<nav><a href='#what'>What Vagar Is</a>"
                 "<a href='#voice'>How Voice Works</a>"
                 "<a href='#skills'>Skills</a>"
                 "<a href='#memory'>Memory</a>"
                 "<a href='#quests'>Quests</a>"
                 "<a href='#talk'>How to Talk to Vagar</a></nav>")
    parts.append("<h1>Vagar Wiki</h1>")
    parts.append("<p><em>Auto-generated from Vagar's own code and memory. "
                 "Local only &mdash; not for sharing.</em></p>")

    # 1. What Vagar is
    parts.append("<h2 id='what'>What Vagar Is</h2>")
    parts.append("<p>Vagar is a fully local, subscription-free voice "
                 "assistant. It runs entirely on your machine &mdash; no cloud, "
                 "no monthly fee, nothing leaves the machine unless asked "
                 "to fetch a public web page.</p>")
    parts.append("<p>Agent code: <code>agent.py</code> (project root). "
                 "Voice calls run over LiveKit (<code>ws://127.0.0.1:7880</code>), "
                 "reachable from a phone over Tailscale. Wake phrase: "
                 "<code>hey vagar</code>.</p>")

    # 2. How voice works
    parts.append("<h2 id='voice'>How Voice Works</h2>")
    pipe = agent.get("pipeline") or \
        "Silero VAD -&gt; faster-whisper STT -&gt; Ollama -&gt; Kokoro-82M TTS"
    parts.append("<div class='pipe'>mic &rarr; %s &rarr; speaker</div>"
                 % _esc(agent.get("pipeline") or
                        "Silero VAD -> faster-whisper STT -> Ollama -> Kokoro-82M TTS"))
    rows = [
        ("Voice activity detection", "Silero VAD (knows when someone is speaking)"),
        ("Speech to text", "faster-whisper <code>%s</code> (offline, English)"
         % _esc(agent.get("stt_model") or "base.en")),
        ("Fast brain", "Ollama <code>%s</code> (quick answers)"
         % _esc(agent.get("fast_model") or "qwen2.5:0.5b")),
        ("Deep brain", "Ollama <code>%s</code> (hard questions)"
         % _esc(agent.get("deep_model") or "qwen2.5:3b")),
        ("Text to speech", "Kokoro-82M, voice <code>%s</code> (British male)"
         % _esc(agent.get("tts_voice") or "bm_lewis")),
        ("Vision", "YOLOv8 object detection + <code>%s</code> rich descriptions"
         % _esc(agent.get("vision_model") or "moondream")),
        ("Transport", "LiveKit (local server, tailnet-only phone app)"),
    ]
    parts.append("<table><tr><th>Stage</th><th>What runs</th></tr>")
    for k, v in rows:
        parts.append("<tr><td>%s</td><td>%s</td></tr>" % (_esc(k), v))
    parts.append("</table>")

    # 3. Skills
    parts.append("<h2 id='skills'>Skills</h2>")
    parts.append("<p>%d skills installed. Each skill is a Python file Vagar "
                 "loads at startup; new skills are drafted locally and only "
                 "go live when the owner approves them.</p>" % len(skills))
    for fn, doc, tools in skills:
        parts.append("<h3><code>%s</code></h3>" % _esc(fn))
        if doc:
            parts.append("<p>%s</p>" % _esc(doc[:400]))
        if tools:
            parts.append("<table><tr><th>Tool</th><th>What it does</th></tr>")
            for name, desc in tools:
                parts.append("<tr><td><code>%s</code></td><td>%s</td></tr>"
                             % (_esc(name), _esc(desc)))
            parts.append("</table>")

    # 4. Memory
    parts.append("<h2 id='memory'>Memory</h2>")
    parts.append("<p>Vagar keeps long-term memory in "
                 "<code>vagar_memory.md</code>. It recalls it at the start of "
                 "every session and saves new facts when asked to "
                 "remember something. Current entries:</p>")
    if memory:
        parts.append("<ul>")
        for b in memory:
            parts.append("<li>%s</li>" % _esc(b))
        parts.append("</ul>")
    else:
        parts.append("<p><em>No memory entries found.</em></p>")

    # 5. Quests
    parts.append("<h2 id='quests'>Quests &amp; XP</h2>")
    xp = quests.get("xp", 0)
    level = quests.get("level", 1)
    thresholds = quests.get("level_thresholds", {})
    parts.append("<p>Level <strong>%d</strong> &mdash; <strong>%d</strong> XP. "
                 % (level, xp))
    if thresholds:
        parts.append("Next levels: " +
                     ", ".join("L%s at %s XP" % (k, v)
                               for k, v in sorted(thresholds.items(),
                                                  key=lambda kv: int(kv[0]))))
    parts.append("</p>")
    active = quests.get("active_quests", [])
    if active:
        parts.append("<h3>Active quests</h3><table>"
                     "<tr><th>Quest</th><th>XP</th><th>Goal</th></tr>")
        for q in active:
            parts.append("<tr><td>%s</td><td>%s</td><td>%s</td></tr>"
                         % (_esc(q.get("name", "")), _esc(str(q.get("xp", ""))),
                            _esc(q.get("description", ""))))
        parts.append("</table>")
    done = quests.get("completed_quests", [])
    if done:
        parts.append("<h3>Completed</h3><ul>")
        for q in done:
            parts.append("<li>%s &mdash; %s</li>"
                         % (_esc(q.get("name", "")),
                            _esc(q.get("description", ""))))
        parts.append("</ul>")

    # 6. How to talk to Vagar
    parts.append("<h2 id='talk'>How to Talk to Vagar</h2>")
    parts.append("<p>Say <code>hey vagar</code>, then talk naturally. "
                 "First sentence of every answer has the point &mdash; no fluff. "
                 "Phrases below come straight from the skill descriptions:</p>")
    if phrases:
        parts.append("<ul>")
        for phrase, tool in phrases:
            parts.append("<li>&ldquo;%s&rdquo; <span style='color:#777'>"
                         "(via <code>%s</code>)</span></li>"
                         % (_esc(phrase), _esc(tool)))
        parts.append("</ul>")
    else:
        parts.append("<p><em>No example phrases found in skill descriptions.</em></p>")
    parts.append("<p>Other things to try: <code>what do you see?</code> (phone "
                 "camera), <code>run a diagnostic</code> (health check), "
                 "<code>what's my quest status?</code>, "
                 "<code>do you know who I am?</code> (speaker check).</p>")

    parts.append("<p class='meta'>Generated %s from live Vagar files. "
                 "Regenerate with <code>wiki_builder.py</code>.</p>" % _esc(now))
    parts.append("</body></html>")

    with open(OUT_PATH, "w", encoding="utf-8") as f:
        f.write("\n".join(parts))
    return OUT_PATH


if __name__ == "__main__":
    print("wiki written to", build())
