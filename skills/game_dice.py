"""Game-night dice for Vagar.

Voice tools:
  roll_die         - roll dice, returns EXACTLY one number (game-night path)
  start_game_night - enable game-night mode (dice spoken as just the number)
  end_game_night   - disable game-night mode, restore normal behavior

The game-night flag lives in game_state.json so agent.py's fast path can
read it without importing this module.
"""
try:
    from livekit.agents.llm import function_tool
except ImportError:  # pragma: no cover - allows unit testing off-laptop
    def function_tool(*_a, **_k):
        def _deco(f):
            return f
        return _deco

import json
import os
import secrets

STATE_PATH = os.path.normpath(os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "game_state.json"))

VALID_SIDES = (4, 6, 8, 10, 12, 20, 100)


def _load_state():
    try:
        with open(STATE_PATH, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


def _save_state(state):
    tmp = STATE_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(state, fh)
    os.replace(tmp, STATE_PATH)


def is_game_night():
    """True when game-night mode is on. Used by agent.py's fast path."""
    return bool(_load_state().get("game_night", False))


@function_tool(
    name="roll_die",
    description=(
        "Roll dice for game night. Returns EXACTLY one number and nothing "
        "else - speak the result back as just the number, no extra words. "
        "Sides must be one of 4, 6, 8, 10, 12, 20, 100. "
        "Count and modifier are optional."
    ),
)
async def roll_die(sides: int = 20, count: int = 1, modifier: int = 0) -> str:
    try:
        s = int(sides)
        c = max(1, int(count))
        m = int(modifier)
    except (TypeError, ValueError):
        return "Say that roll again - I need numbers."
    if s not in VALID_SIDES:
        return "I roll d4, d6, d8, d10, d12, d20, or d100."
    if c > 20:
        return "Keep it to twenty dice or fewer."
    total = sum(secrets.randbelow(s) + 1 for _ in range(c)) + m
    return str(total)


@function_tool(
    name="start_game_night",
    description=(
        "Start game-night mode: dice results are spoken as exactly one "
        "number with no flavor. Call when the user says game night is starting."
    ),
)
async def start_game_night() -> str:
    state = _load_state()
    state["game_night"] = True
    _save_state(state)
    return "Game-night mode on. Dice will be just the number."


@function_tool(
    name="end_game_night",
    description="End game-night mode and restore normal Vagar behavior.",
)
async def end_game_night() -> str:
    state = _load_state()
    state["game_night"] = False
    _save_state(state)
    return "Game-night mode off."
