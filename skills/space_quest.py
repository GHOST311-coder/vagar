"""Space Quest skill for Vagar â€” alien contact & paranormal boss battles.

Voice tools:
  whats_overhead      - where is the ISS right now, is it visible overhead
  space_science       - explain SETI / radio astronomy topics (Drake Equation,
                        Wow! Signal, Fermi Paradox, Jupiter radio storms, etc.)
  quest_progress      - show boss battle progress for the space quests
  paranormal_brief    - honest briefing on paranormal investigation tools
                        (EVP, EMF) with a skeptical, evidence-first framing

All data sources are free with no API keys. The ISS position comes from the
free wheretheiss.at API. Set HOME_LAT/HOME_LON below to your location.
"""
try:
    from livekit.agents.llm import function_tool
except ImportError:  # pragma: no cover - allows unit testing off-laptop
    def function_tool(*_a, **_k):
        def _deco(f):
            return f
        return _deco

import json
import math
import os
import urllib.request

# Your location - set these to your coordinates
HOME_LAT = float(os.environ.get("VAGAR_HOME_LAT", "0.0"))  # e.g. 30.62
HOME_LON = float(os.environ.get("VAGAR_HOME_LON", "0.0"))  # e.g. -89.65

ISS_API = "https://api.wheretheiss.at/v1/satellites/25544"

# Curated science explainers (short, voice-friendly, no markdown in output)
_SCIENCE = {
    "drake equation": (
        "The Drake Equation estimates how many detectable civilizations might "
        "exist in our galaxy. It multiplies: stars formed per year, fraction with "
        "planets, habitable planets per system, fraction where life starts, "
        "fraction developing intelligence, fraction broadcasting signals, and how "
        "long they broadcast. The honest answer: we can guess the first three "
        "terms from telescope data, but the last four are pure speculation. "
        "Estimates range from one â€” just us â€” to millions."
    ),
    "wow signal": (
        "The Wow Signal was a strong narrowband radio burst detected on "
        "August 15th, 1977, by Ohio State's Big Ear telescope. It lasted 72 "
        "seconds, came from the direction of Sagittarius, and matched what an "
        "interstellar beacon might look like. It never repeated despite many "
        "follow-up searches. A 2024 reanalysis suggests it may have been a "
        "rare astrophysical event â€” a stellar flare lighting up a cold hydrogen "
        "cloud â€” rather than a transmission. Still the most famous candidate "
        "signal in SETI history."
    ),
    "fermi paradox": (
        "The Fermi Paradox asks: if the galaxy is old and full of stars, where "
        "is everybody? Proposed answers include the Great Filter â€” some step "
        "from dead matter to starfaring civilization is extremely hard, and we "
        "don't know if it's behind us or ahead. Other ideas: we're listening on "
        "the wrong channels, they're deliberately quiet, or interstellar travel "
        "is just too costly even for advanced species."
    ),
    "jupiter radio": (
        "Jupiter is the loudest radio planet in our sky. Its magnetic field is "
        "20,000 times stronger than Earth's, and charged particles spiraling in "
        "it blast out radio waves around 20 megahertz. It sounds like ocean "
        "surf mixed with popcorn popping. NASA's Radio JOVE project lets anyone "
        "listen with a simple shortwave receiver. Best heard late at night when "
        "Jupiter is up and the ionosphere cooperates."
    ),
    "seti": (
        "SETI, the Search for Extraterrestrial Intelligence, listens for radio "
        "or laser signals that nature wouldn't produce â€” narrowband beacons, "
        "repeating patterns, that kind of thing. SETI at Home, the famous "
        "volunteer project, wrapped up analysis in 2026 after narrowing 12 "
        "billion detections down to 100 targets now being followed up by "
        "China's FAST telescope. Today, volunteers can join through BOINC and "
        "Einstein at Home, or classify real signals on Zooniverse's Are We "
        "Alone project."
    ),
}


def _fetch_json(url, timeout=12):
    req = urllib.request.Request(url, headers={"User-Agent": "Vagar/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def _haversine_km(lat1, lon1, lat2, lon2):
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def _quest_file():
    return os.path.normpath(os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "..", "quests.json"))


@function_tool(
    name="whats_overhead",
    description=(
        "Where is the International Space Station right now, and is it near "
        "or visible over your location? Use when he asks "
        "what's overhead, where's the ISS, or about satellite passes."
    ),
)
async def whats_overhead() -> str:
    try:
        d = _fetch_json(ISS_API)
    except Exception as e:
        return "I couldn't reach the ISS tracker just now: %s" % e
    lat = d.get("latitude")
    lon = d.get("longitude")
    alt = d.get("altitude")
    vel = d.get("velocity")
    if lat is None or lon is None:
        return "The ISS tracker returned incomplete data. Try again in a minute."
    dist = _haversine_km(HOME_LAT, HOME_LON, lat, lon)
    # ISS visible roughly within ~2,300 km ground distance at good passes
    if dist < 1200:
        near = "It's close â€” about %d km away. Check Heavens-Above for exact pass times." % int(dist)
    elif dist < 2300:
        near = "It's about %d km away â€” possibly visible on a good pass." % int(dist)
    else:
        near = "It's about %d km away â€” not overhead right now." % int(dist)
    return (
        "The ISS is currently at %.1f degrees latitude, %.1f degrees longitude, "
        "altitude %.0f km, moving at %.0f km/h. %s"
        % (lat, lon, alt or 0, vel or 0, near)
    )


@function_tool(
    name="space_science",
    description=(
        "Explain a space/SETI science topic: drake equation, wow signal, fermi "
        "paradox, jupiter radio, or seti. Use when the user asks about the science "
        "behind the alien contact quest."
    ),
)
async def space_science(topic: str = "") -> str:
    key = (topic or "").strip().lower()
    for name, text in _SCIENCE.items():
        if name in key or key in name:
            return text
    return (
        "I can explain: the Drake Equation, the Wow Signal, the Fermi Paradox, "
        "Jupiter's radio storms, or SETI itself. Which one?"
    )


@function_tool(
    name="quest_progress",
    description=(
        "Show the user's progress on the boss battles: The Signal in the Static "
        "(alien contact) and The Veil Between Worlds (paranormal). Use when he "
        "asks about quest status or boss battles."
    ),
)
async def quest_progress() -> str:
    path = _quest_file()
    try:
        with open(path, "r", encoding="utf-8") as f:
            q = json.load(f)
    except Exception as e:
        return "Couldn't read the quest file: %s" % e
    active = q.get("active") or []
    if not active:
        return "No active boss battles right now."
    lines = []
    for b in active:
        name = b.get("name", "unknown")
        phase = b.get("phase", 1)
        objectives = b.get("objectives") or []
        lines.append("%s (phase %s): %d objectives" % (name, phase, len(objectives)))
        for o in objectives[:4]:
            lines.append("  - " + o)
    return "\n".join(lines)


@function_tool(
    name="paranormal_brief",
    description=(
        "Give an honest, evidence-first briefing on paranormal investigation "
        "tools (EVP recorders, EMF meters). Skeptical framing: these are real "
        "devices used as a hobby, but there is no scientific evidence they "
        "detect anything paranormal. Use when the user asks about the paranormal "
        "boss battle."
    ),
)
async def paranormal_brief(topic: str = "") -> str:
    t = (topic or "").lower()
    if "evp" in t:
        return (
            "EVP â€” electronic voice phenomena â€” means apparent voices on audio "
            "recordings that weren't heard live. Investigators use sensitive "
            "digital recorders and amplify quiet sections. The skeptical view: "
            "most EVPs are pareidolia â€” the brain finding voices in random "
            "noise â€” plus radio interference and recorder artifacts. As a "
            "hobby build, a good recorder and free audio software like Audacity "
            "is all you need. No evidence any EVP has ever been a genuine "
            "paranormal voice."
        )
    if "emf" in t:
        return (
            "EMF meters measure electromagnetic fields. Paranormal investigators "
            "treat spikes as possible spirit activity. The skeptical view: "
            "wiring, appliances, and phones cause spikes constantly, and there's "
            "no established link between EMF readings and anything paranormal. "
            "As a gadget it's real â€” a basic meter costs about 25 dollars â€” "
            "but it detects wiring, not ghosts."
        )
    return (
        "For the paranormal boss battle: EVP recorders and EMF meters are real "
        "devices and a genuine hobby, but I have to be straight â€” there's no "
        "scientific evidence they detect anything paranormal. I can brief you "
        "on EVP or EMF specifically, or help plan an investigation with a "
        "skeptic's checklist: rule out mundane causes first, log everything."
    )
