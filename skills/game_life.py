"""Game-night life tracker for Vagar (Commander, 40 life).

Voice tools:
  new_game    - start a game with player names
  deal_damage - record damage to a player
  gain_life   - record life gained by a player
  get_totals  - report every player's current life total
  reset_game  - clear the table

State persists in game_state.json so totals survive restarts.
Silent between turns: tools only speak when their result is returned.
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

STATE_PATH = os.path.normpath(os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "game_state.json"))

STARTING_LIFE = 40


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


def _players(state):
    return state.setdefault("players", {})


def _find(state, name):
    """Case-insensitive player lookup. Returns (key, life) or (None, None)."""
    want = (name or "").strip().lower()
    for key, life in _players(state).items():
        if key.lower() == want:
            return key, life
    return None, None


@function_tool(
    name="new_game",
    description=(
        "Start a new Commander game. Give player names as a comma-separated "
        "list, e.g. 'Player1, Player2, Player3'. Everyone starts at 40 life."
    ),
)
async def new_game(players: str) -> str:
    names = [p.strip() for p in (players or "").split(",") if p.strip()]
    if not names:
        return "Tell me the player names to start the game."
    state = _load_state()
    state["players"] = {n: STARTING_LIFE for n in names}
    _save_state(state)
    return "Game on. %s, all at 40." % ", ".join(names)


@function_tool(
    name="deal_damage",
    description=(
        "Record damage dealt to a player, e.g. Mike takes 3 damage. "
        "Speaks the player's new total back."
    ),
)
async def deal_damage(player: str, amount: int) -> str:
    try:
        dmg = int(amount)
    except (TypeError, ValueError):
        return "How much damage?"
    if dmg < 0:
        return "Damage can't be negative."
    state = _load_state()
    key, life = _find(state, player)
    if key is None:
        return "I don't have a player named %s." % (player or "that")
    life -= dmg
    state["players"][key] = life
    _save_state(state)
    if life <= 0:
        return "%s is out." % key
    return "%s at %d." % (key, life)


@function_tool(
    name="gain_life",
    description=(
        "Record life gained by a player, e.g. Player1 gains 5 life. "
        "Speaks the player's new total back."
    ),
)
async def gain_life(player: str, amount: int) -> str:
    try:
        amt = int(amount)
    except (TypeError, ValueError):
        return "How much life?"
    if amt < 0:
        return "Life gain can't be negative."
    state = _load_state()
    key, life = _find(state, player)
    if key is None:
        return "I don't have a player named %s." % (player or "that")
    life += amt
    state["players"][key] = life
    _save_state(state)
    return "%s at %d." % (key, life)


@function_tool(
    name="get_totals",
    description="Report every player's current life total.",
)
async def get_totals() -> str:
    state = _load_state()
    players = _players(state)
    if not players:
        return "No game running. Start one with new_game."
    parts = ["%s %d" % (k, v) for k, v in players.items()]
    return "Life totals: " + ", ".join(parts) + "."


@function_tool(
    name="reset_game",
    description="Clear the table and end the current game.",
)
async def reset_game() -> str:
    state = _load_state()
    state["players"] = {}
    _save_state(state)
    return "Table cleared."
