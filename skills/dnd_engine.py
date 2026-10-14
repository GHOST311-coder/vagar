"""Full D&D 5e rules engine for Vagar.

Real mechanics from the D&D SRD 5.1 (CC BY 4.0, (c) Wizards of the Coast).
Rules text lookups go through the dnd_mtg skill (search_dnd_rules) which
queries the local SRD knowledge base.

BOUNDARY: SRD content only. No adventures, no setting guides, no
copyrighted monsters or subclasses. Dungeon monsters below are all
SRD 5.1 stat blocks (or simplified from them). Bosses are original
creations for the player's real-life quests, built on 5e math.

State lives in dnd_state.json next to this file. Character flavor
(weapons/items/spells names) lives in quests.json via quest_manager;
this engine owns the MECHANICS (ability scores, HP, slots, combat).

Voice tools are @function_tool async defs at the bottom.
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
import re
import secrets
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
try:
    import quest_manager as qm
except ImportError:
    qm = None

STATE_PATH = os.path.normpath(os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "dnd_state.json"))

# ---------------------------------------------------------------- dice ---

def _d(sides):
    return secrets.randbelow(sides) + 1


def roll_dice_expr(expr):
    """Parse NdM+K (e.g. '2d6+3', 'd20', '4d8-2'). Returns (total, detail)."""
    m = re.fullmatch(r"\s*(\d*)d(\d+)\s*([+-]\s*\d+)?\s*", expr or "")
    if not m:
        raise ValueError("bad dice expression: %r" % expr)
    n = int(m.group(1)) if m.group(1) else 1
    sides = int(m.group(2))
    mod = int(m.group(3).replace(" ", "")) if m.group(3) else 0
    if n < 1 or n > 100 or sides < 2 or sides > 1000:
        raise ValueError("dice out of range: %r" % expr)
    rolls = [_d(sides) for _ in range(n)]
    total = sum(rolls) + mod
    detail = "%s%s%+d = %d" % (
        "%dd%d" % (n, sides), rolls, mod, total) if mod else "%s%s = %d" % (
        "%dd%d" % (n, sides), rolls, total)
    return total, detail


# ------------------------------------------------------- abilities ---

ABILITIES = ["STR", "DEX", "CON", "INT", "WIS", "CHA"]

# the player's Artificer: builder's spread, high INT.
BASE_SCORES = {
    "STR": 12, "DEX": 14, "CON": 14, "INT": 16, "WIS": 12, "CHA": 10,
}

SKILL_ABILITY = {
    "acrobatics": "DEX", "animal handling": "WIS", "arcana": "INT",
    "athletics": "STR", "deception": "CHA", "history": "INT",
    "insight": "WIS", "intimidation": "CHA", "investigation": "INT",
    "medicine": "WIS", "nature": "INT", "perception": "WIS",
    "performance": "CHA", "persuasion": "CHA", "religion": "INT",
    "sleight of hand": "DEX", "stealth": "DEX", "survival": "WIS",
}

# Artificer proficiencies (SRD 5.1): light/medium armor, shields,
# simple weapons; saves CON + INT; tools: thieves', tinker's, one artisan.
ARTIFICER_SKILL_PROFS = [
    "arcana", "investigation", "perception", "sleight of hand",
]
ARTIFICER_SAVE_PROFS = ["CON", "INT"]


def ability_mod(score):
    return (score - 10) // 2


def proficiency_bonus(level):
    return 2 + (level - 1) // 4


def artificer_spell_slots(level):
    # SRD 5.1 Artificer table (1st-level slots only at these levels)
    return {1: 2, 2: 2, 3: 3}.get(level, 3)


def _default_state():
    return {
        "character": {
            "name": "the player",
            "class": "Artificer",
            "level": 3,
            "scores": dict(BASE_SCORES),
            "hp": 22,
            "max_hp": 22,
            "ac": 16,  # studded leather (12+2 DEX) + shield
            "spell_slots": {"1": artificer_spell_slots(3)},
            "spell_slots_max": {"1": artificer_spell_slots(3)},
            "prepared": ["comprehend languages", "identify", "alarm",
                         "cure wounds", "faerie fire", "sanctuary"],
            "infusions_known": ["Enhanced Defense", "Enhanced Weapon",
                                "Replicate Magic Item"],
            "infused": ["Everbright Multitool"],
            "conditions": [],
            "death_saves": {"success": 0, "fail": 0},
            "xp_dnd": 0,
        },
        "combat": None,  # or {"round": n, "order": [...], "turn": idx}
        "quests": {},
        "dungeon": None,
    }


def _load():
    try:
        with open(STATE_PATH, "r", encoding="utf-8") as fh:
            st = json.load(fh)
        # migrate: ensure keys exist
        d = _default_state()
        for k, v in d.items():
            st.setdefault(k, v)
        return st
    except (OSError, ValueError):
        return _default_state()


def _save(st):
    tmp = STATE_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(st, fh, indent=2)
    os.replace(tmp, STATE_PATH)


def _char(st):
    return st["character"]


def _mod_for(st, ability):
    return ability_mod(_char(st)["scores"][ability.upper()])


def _skill_bonus(st, skill):
    skill = skill.lower().strip()
    ab = SKILL_ABILITY.get(skill)
    if not ab:
        return None
    bonus = _mod_for(st, ab)
    if skill in ARTIFICER_SKILL_PROFS:
        bonus += proficiency_bonus(_char(st)["level"])
    return bonus

# ---------------------------------------------------------- combat ---

def _new_combatant(name, hp, ac, is_enemy=False, dex_mod=0):
    return {"name": name, "hp": hp, "max_hp": hp, "ac": ac,
            "is_enemy": is_enemy, "dex_mod": dex_mod,
            "initiative": None, "conditions": [],
            "death_saves": {"success": 0, "fail": 0}}


def _combat_text(st):
    c = st["combat"]
    if not c:
        return "No combat running."
    lines = ["Combat - round %d. Turn: %s." % (
        c["round"], c["order"][c["turn"]]["name"])]
    for i, m in enumerate(c["order"]):
        marker = ">> " if i == c["turn"] else "   "
        cond = " [%s]" % ",".join(m["conditions"]) if m["conditions"] else ""
        ds = m["death_saves"]
        dying = ""
        if m["hp"] <= 0 and not m["is_enemy"]:
            dying = " (death saves %d/%d)" % (ds["success"], ds["fail"])
        lines.append("%s%s: %d/%d HP, AC %d%s%s" % (
            marker, m["name"], max(m["hp"], 0), m["max_hp"], m["ac"],
            cond, dying))
    return "\n".join(lines)


# ----------------------------------------------------------- bosses ---

# Original creations for the player's real-life quests. 5e math, SRD-style.
BOSSES = {
    "the static": {
        "title": "The Static, Voice of the Dead Air",
        "quest": "The Signal in the Static",
        "flavor": ("A rogue broadcast that learned to hate silence. It wears "
                   "dead channels like armor and screams through every "
                   "frequency at once. the player faces it every time he pushes "
                   "Vagar's repo public."),
        "type": "Large aberration", "ac": 15, "hp": 120,
        "speed": "30 ft., fly 30 ft.",
        "scores": {"STR": 10, "DEX": 16, "CON": 14,
                   "INT": 18, "WIS": 12, "CHA": 8},
        "attacks": [
            {"name": "Psychic Burst", "to_hit": 6, "dmg": "2d8",
             "dtype": "psychic"},
            {"name": "Feedback Screech (Recharge 5-6)", "dc": 14,
             "save": "INT", "effect": "stunned until end of its next turn",
             "dmg": "3d6", "dtype": "thunder"},
        ],
        "phases": [
            (60, "SIGNAL BOOST: The Static gains Multiattack (two Psychic Bursts)."),
            (30, "DEAD AIR: legendary action - Psychic Lash +6, 1d10 psychic."),
        ],
        "loot": ["Echo of the First Broadcast (wondrous item)",
                 "250 XP toward the Friday Launch"],
    },
    "the veilwarden": {
        "title": "The Veilwarden, Keeper of the Threshold",
        "quest": "The Veil Between Worlds",
        "flavor": ("It stands where the living world thins - part grief, "
                   "part static, all hunger. It does not want to cross over. "
                   "It wants to pull you through."),
        "type": "Medium undead", "ac": 14, "hp": 95,
        "speed": "30 ft.",
        "scores": {"STR": 14, "DEX": 14, "CON": 12,
                   "INT": 10, "WIS": 16, "CHA": 14},
        "attacks": [
            {"name": "Veil Rend", "to_hit": 5, "dmg": "2d6+3",
             "dtype": "necrotic"},
            {"name": "Grasp Beyond", "dc": 13, "save": "WIS",
             "effect": "frightened for 1 minute (repeat save each turn)",
             "dmg": "1d8", "dtype": "cold"},
        ],
        "phases": [
            (48, "THINNING: the Veilwarden can move through creatures and "
                 "objects as if difficult terrain."),
            (24, "LAST GASP: legendary action - Chilling Touch +5, 1d8 cold."),
        ],
        "loot": ["Shroud of the Threshold (cloak, +1 AC vs undead)",
                 "200 XP toward the Friday Launch"],
    },
    "babel": {
        "title": "Babel, the Tongue-Twister",
        "quest": "The Polyglot Engine (translation layer)",
        "flavor": ("Two hundred voices speaking at once and none of them "
                   "listening. Babel scrambles meaning itself - the final "
                   "guardian of the translation layer."),
        "type": "Large construct", "ac": 16, "hp": 110,
        "speed": "25 ft.",
        "scores": {"STR": 16, "DEX": 10, "CON": 16,
                   "INT": 14, "WIS": 10, "CHA": 6},
        "attacks": [
            {"name": "Slam", "to_hit": 6, "dmg": "2d8+3",
             "dtype": "bludgeoning"},
            {"name": "Word Scramble (Recharge 6)", "dc": 14, "save": "INT",
             "effect": "cannot speak or cast spells with verbal components "
                       "for 1 minute (repeat save each turn)",
             "dmg": "2d6", "dtype": "psychic"},
        ],
        "phases": [
            (55, "OVERLOAD: Babel gains Multiattack (two Slams)."),
            (28, "CASCADE FAILURE: legendary action - Garbled Command, "
                 "DC 13 WIS or attack nearest ally."),
        ],
        "loot": ["The Rosetta Core (wondrous item: +2 Arcana, comprehend "
                 "languages at will)", "300 XP"],
    },
}


def _boss_combatant(key):
    b = BOSSES[key]
    return _new_combatant(b["title"], b["hp"], b["ac"], is_enemy=True,
                         dex_mod=ability_mod(b["scores"]["DEX"]))


# ------------------------------------------------------------ quests ---

# the player's REAL active quests, mapped as D&D quest entries.
REAL_QUESTS = {
    "dragons_hoard": {
        "title": "The Dragon's Hoard",
        "real": "50-dragon Cozy Dragons art batch",
        "kind": "dungeon",
        "brief": ("A vault of fifty chambers. Each approved dragon page "
                  "clears one room. The hoard grows with every clean page."),
        "objective": "Approve 50 colorable dragon pages (0/50 cleared)",
        "xp": 500, "progress": 0, "goal": 50,
    },
    "polyglot": {
        "title": "The Polyglot Engine",
        "real": "200-language translation layer for Vagar",
        "kind": "boss",
        "brief": "Build the engine, then face Babel, the Tongue-Twister.",
        "objective": "Finish the translation layer build",
        "xp": 300, "progress": 0, "goal": 1, "boss": "babel",
    },
    "five_tales": {
        "title": "The Five Tales",
        "real": "5-episode faceless video pipeline",
        "kind": "chain",
        "brief": ("Five stories, one every five hours. The Watchers opened "
                  "the telling; four tales remain."),
        "objective": "Complete all 5 episodes (1/5 done)",
        "xp": 400, "progress": 1, "goal": 5,
    },
    "signal": {
        "title": "The Signal in the Static",
        "real": "Push Vagar to GitHub (public release)",
        "kind": "boss",
        "brief": "Face The Static and broadcast Vagar to the world.",
        "objective": "Resolve the branch, push the repo",
        "xp": 250, "progress": 0, "goal": 1, "boss": "the static",
    },
    "veil": {
        "title": "The Veil Between Worlds",
        "real": "Paranormal investigation with Vagar",
        "kind": "boss",
        "brief": "Research EVP/EMF, build the tools, face the Veilwarden.",
        "objective": "Complete phase 1 research + tool build",
        "xp": 200, "progress": 0, "goal": 1, "boss": "the veilwarden",
    },
}


def _quest_text(st):
    qs = st["quests"]
    if not qs:
        for k, v in REAL_QUESTS.items():
            qs[k] = dict(v)
        _save(st)
    lines = ["the player's quests (real work, D&D frame):"]
    for k, q in qs.items():
        if q["kind"] == "dungeon":
            prog = "%d/%d rooms" % (q["progress"], q["goal"])
        elif q["kind"] == "chain":
            prog = "%d/%d tales" % (q["progress"], q["goal"])
        else:
            prog = "done" if q["progress"] >= q["goal"] else "open"
        lines.append("- %s [%s]: %s (%d XP)" % (
            q["title"], prog, q["brief"], q["xp"]))
    return "\n".join(lines)


# ---------------------------------------------------------- dungeon ---

# SRD 5.1 monsters (simplified stat blocks, all from the SRD).
SRD_MONSTERS = [
    {"name": "Giant Rat", "ac": 12, "hp": 7, "to_hit": 4, "dmg": "1d6+2",
     "dtype": "piercing", "xp": 25},
    {"name": "Goblin", "ac": 15, "hp": 7, "to_hit": 4, "dmg": "1d6+2",
     "dtype": "slashing", "xp": 50},
    {"name": "Skeleton", "ac": 13, "hp": 13, "to_hit": 4, "dmg": "1d6+2",
     "dtype": "piercing", "xp": 50},
    {"name": "Zombie", "ac": 8, "hp": 22, "to_hit": 3, "dmg": "1d6+1",
     "dtype": "bludgeoning", "xp": 50},
    {"name": "Orc", "ac": 13, "hp": 15, "to_hit": 5, "dmg": "1d12+3",
     "dtype": "slashing", "xp": 100},
    {"name": "Ogre", "ac": 11, "hp": 59, "to_hit": 6, "dmg": "2d8+4",
     "dtype": "bludgeoning", "xp": 450},
]

TRAPS = [
    {"name": "poison darts", "dc": 13, "save": "DEX", "dmg": "2d4",
     "dtype": "piercing"},
    {"name": "swinging blade", "dc": 14, "save": "DEX", "dmg": "2d10",
     "dtype": "slashing"},
    {"name": "collapsing ceiling", "dc": 15, "save": "DEX", "dmg": "4d6",
     "dtype": "bludgeoning"},
]

LOOT_COMMON = [
    "Potion of Healing", "50 gp in mixed coin", "a silvered dagger",
    "Alchemist's fire (flask)", "Bag of 200 ball bearings",
]
LOOT_RARE = [
    "+1 Weapon (your choice, via award_item)",
    "Cloak of Protection",
    "Boots of Elvenkind",
    "Wand of Magic Detection",
]


def _gen_dungeon(depth=3):
    rooms = []
    for i in range(1, depth + 1):
        r = secrets.randbelow(100)
        if r < 35:
            mon = secrets.choice(SRD_MONSTERS)
            rooms.append({"n": i, "kind": "monster", "what": dict(mon)})
        elif r < 60:
            trap = secrets.choice(TRAPS)
            rooms.append({"n": i, "kind": "trap", "what": dict(trap)})
        elif r < 80:
            loot = secrets.choice(LOOT_COMMON)
            rooms.append({"n": i, "kind": "treasure", "what": loot})
        else:
            rooms.append({"n": i, "kind": "empty",
                          "what": "dust and old echoes"})
    # boss room at the end
    boss_mon = secrets.choice([m for m in SRD_MONSTERS if m["xp"] >= 100])
    rooms.append({"n": depth + 1, "kind": "boss", "what": dict(boss_mon),
                  "note": "room boss"})
    return {"depth": depth + 1, "rooms": rooms, "at": 0, "cleared": 0}

# ------------------------------------------------------ voice tools ---

@function_tool(
    name="roll_check",
    description=("Make a D&D ability or skill check for the player. skill examples: "
                "perception, arcana, investigation, athletics, stealth. Or pass "
                "an ability: STR, DEX, CON, INT, WIS, CHA. Rolls d20 plus "
                "the player's real Artificer modifiers. Use when he attempts "
                "something uncertain."),
)
async def roll_check(skill: str) -> str:
    st = _load()
    skill = (skill or "").strip()
    up = skill.upper()
    if up in ABILITIES:
        bonus = _mod_for(st, up)
        label = up
    else:
        bonus = _skill_bonus(st, skill)
        if bonus is None:
            return "No such skill: %s." % skill
        label = skill.lower()
    nat = _d(20)
    total = nat + bonus
    crit = " Critical success!" if nat == 20 else (
        " Critical fail." if nat == 1 else "")
    return "%s check: d20(%d)%+d = %d.%s" % (label, nat, bonus, total, crit)


@function_tool(
    name="roll_save",
    description=("the player makes a D&D saving throw. ability: STR/DEX/CON/INT/"
                "WIS/CHA. Uses his Artificer save proficiencies (CON, INT)."),
)
async def roll_save(ability: str) -> str:
    st = _load()
    up = (ability or "").upper().strip()
    if up not in ABILITIES:
        return "Ability must be one of: %s." % ", ".join(ABILITIES)
    bonus = _mod_for(st, up)
    if up in ARTIFICER_SAVE_PROFS:
        bonus += proficiency_bonus(_char(st)["level"])
        tag = " (proficient)"
    else:
        tag = ""
    nat = _d(20)
    return "%s save%s: d20(%d)%+d = %d." % (up, tag, nat, bonus, nat + bonus)


@function_tool(
    name="attack_roll",
    description=("the player attacks in D&D. weapon: 'wrench' (Wrench of the Long "
                "Haul, 1d8 bludgeoning, STR) or 'conduit' (The Hermes Conduit, "
                "1d6 lightning, INT spell attack). target_ac: the foe's AC. "
                "Rolls to hit, then damage on a hit."),
)
async def attack_roll(weapon: str, target_ac: int) -> str:
    st = _load()
    ch = _char(st)
    w = (weapon or "").lower()
    if "wrench" in w:
        atk_bonus = _mod_for(st, "STR") + proficiency_bonus(ch["level"])
        dmg_expr, dtype = "1d8", "bludgeoning"
        dmg_bonus = _mod_for(st, "STR")
        wname = "Wrench of the Long Haul"
    elif "conduit" in w:
        atk_bonus = _mod_for(st, "INT") + proficiency_bonus(ch["level"])
        dmg_expr, dtype = "1d6", "lightning"
        dmg_bonus = 0
        wname = "The Hermes Conduit"
    else:
        return "Weapon must be 'wrench' or 'conduit'."
    nat = _d(20)
    total = nat + atk_bonus
    if nat == 20:
        dmg, detail = roll_dice_expr("2" + dmg_expr[1:] + "%+d" % dmg_bonus)
        return ("%s attacks with %s: NATURAL 20! Critical hit for %d %s "
                "damage (%s)." % (ch["name"], wname, dmg, dtype, detail))
    if nat == 1:
        return ("%s attacks with %s: natural 1. Miss, and the wrench "
                "clatters." % (ch["name"], wname))
    if total >= target_ac:
        dmg, detail = roll_dice_expr("%s%+d" % (dmg_expr, dmg_bonus))
        return ("%s attacks with %s: %d vs AC %d - HIT for %d %s damage "
                "(%s)." % (ch["name"], wname, total, target_ac, dmg, dtype,
                           detail))
    return ("%s attacks with %s: %d vs AC %d - miss." % (
        ch["name"], wname, total, target_ac))


@function_tool(
    name="cast_spell",
    description=("the player casts a D&D spell. Uses his Artificer spell slots. "
                "Known: mending, guidance (cantrips, free); comprehend "
                "languages, identify, alarm, cure wounds, faerie fire, "
                "sanctuary (1st level, cost 1 slot)."),
)
async def cast_spell(spell_name: str) -> str:
    st = _load()
    ch = _char(st)
    s = (spell_name or "").lower().strip()
    cantrips = {"mending": "You mend a break or tear - the truck, the code, "
                           "the day. One minute, good as new.",
                "guidance": "You touch an ally (or yourself): +1d4 on one "
                            "ability check within the minute. Always double "
                            "check yourself."}
    if s in cantrips:
        return "%s casts %s. %s" % (ch["name"], s.title(), cantrips[s])
    if s not in ch["prepared"]:
        return ("%s isn't prepared. Prepared: %s." % (
            spell_name, ", ".join(ch["prepared"])))
    if ch["spell_slots"].get("1", 0) <= 0:
        return "No 1st-level slots left. Take a long rest."
    ch["spell_slots"]["1"] -= 1
    _save(st)
    effects = {
        "comprehend languages": "For one hour you understand any spoken or "
            "written language. Two hundred tongues, one mind.",
        "identify": "You learn the true properties of one magic item. "
            "The fact-checker's spell.",
        "alarm": "You ward an area for 8 hours. The tripwire hums.",
        "cure wounds": None,  # handled with healing below
        "faerie fire": "DC 13 DEX or outlined in light: attacks against "
            "affected creatures have advantage for 1 minute.",
        "sanctuary": "One creature you touch is warded: attackers must make "
            "a DC 13 WIS save or choose a new target.",
    }
    if s == "cure wounds":
        amt, detail = roll_dice_expr("1d8+%d" % _mod_for(st, "INT"))
        ch["hp"] = min(ch["max_hp"], ch["hp"] + amt)
        _save(st)
        return ("%s casts Cure Wounds: heals %d HP (%s). Now %d/%d. "
                "%d slot(s) left." % (ch["name"], amt, detail, ch["hp"],
                                      ch["max_hp"], ch["spell_slots"]["1"]))
    return ("%s casts %s (%d slot(s) left). %s" % (
        ch["name"], s.title(), ch["spell_slots"]["1"], effects.get(s, "")))


@function_tool(
    name="take_damage",
    description="the player takes damage in D&D. Reduces HP, tracks death saves "
                "at 0 HP.",
)
async def take_damage(amount: int) -> str:
    st = _load()
    ch = _char(st)
    ch["hp"] = max(0, ch["hp"] - max(0, int(amount)))
    msg = "%s takes %d damage: %d/%d HP." % (
        ch["name"], amount, ch["hp"], ch["max_hp"])
    if ch["hp"] == 0:
        msg += " DOWN! Death saves begin."
    _save(st)
    return msg


@function_tool(
    name="heal",
    description="the player regains HP in D&D (potion, rest, ally).",
)
async def heal(amount: int) -> str:
    st = _load()
    ch = _char(st)
    ch["hp"] = min(ch["max_hp"], ch["hp"] + max(0, int(amount)))
    ch["death_saves"] = {"success": 0, "fail": 0}
    _save(st)
    return "%s heals %d: %d/%d HP." % (ch["name"], amount, ch["hp"],
                                       ch["max_hp"])


@function_tool(
    name="death_save",
    description="Roll a D&D death saving throw (only at 0 HP). 3 successes "
                "stabilize, 3 fails mean death. Nat 20: regain 1 HP.",
)
async def death_save() -> str:
    st = _load()
    ch = _char(st)
    if ch["hp"] > 0:
        return "Not dying - %d/%d HP." % (ch["hp"], ch["max_hp"])
    nat = _d(20)
    ds = ch["death_saves"]
    if nat == 20:
        ch["hp"] = 1
        ch["death_saves"] = {"success": 0, "fail": 0}
        _save(st)
        return "NATURAL 20! %s surges back with 1 HP." % ch["name"]
    if nat == 1:
        ds["fail"] += 2
    elif nat >= 10:
        ds["success"] += 1
    else:
        ds["fail"] += 1
    _save(st)
    if ds["fail"] >= 3:
        return "Death save %d: three failures. %s falls." % (nat, ch["name"])
    if ds["success"] >= 3:
        return "Death save %d: stabilized at 0 HP." % nat
    return "Death save %d: %d success, %d fail." % (nat, ds["success"],
                                                   ds["fail"])


@function_tool(
    name="short_rest",
    description="D&D short rest (1 hour): spend hit dice to heal. Artificer "
                "hit die is d8.",
)
async def short_rest() -> str:
    st = _load()
    ch = _char(st)
    con = _mod_for(st, "CON")
    amt, detail = roll_dice_expr("1d8%+d" % con)
    ch["hp"] = min(ch["max_hp"], ch["hp"] + amt)
    _save(st)
    return "Short rest. %s spends a hit die, heals %d (%s): %d/%d HP." % (
        ch["name"], amt, detail, ch["hp"], ch["max_hp"])


@function_tool(
    name="long_rest",
    description="D&D long rest (8 hours): full HP, all spell slots restored, "
                "conditions cleared.",
)
async def long_rest() -> str:
    st = _load()
    ch = _char(st)
    ch["hp"] = ch["max_hp"]
    ch["spell_slots"] = dict(ch["spell_slots_max"])
    ch["conditions"] = []
    ch["death_saves"] = {"success": 0, "fail": 0}
    _save(st)
    return ("Long rest complete. %s is at %d/%d HP, spell slots restored, "
            "ready to build." % (ch["name"], ch["hp"], ch["max_hp"]))


@function_tool(
    name="show_character",
    description="Show the player's full D&D character sheet: Artificer level, "
                "ability scores, HP, AC, spell slots, saves, skills. Use when "
                "he asks about his character, stats, or sheet.",
)
async def show_character() -> str:
    st = _load()
    ch = _char(st)
    lvl = ch["level"]
    pb = proficiency_bonus(lvl)
    lines = [
        "the player - Level %d Artificer (HP %d/%d, AC %d)" % (
            lvl, ch["hp"], ch["max_hp"], ch["ac"]),
        "STR %d (%+d)  DEX %d (%+d)  CON %d (%+d)  INT %d (%+d)  "
        "WIS %d (%+d)  CHA %d (%+d)" % tuple(
            v for s in ABILITIES for v in (ch["scores"][s],
                                           ability_mod(ch["scores"][s]))),
        "Proficiency +%d | Saves: CON, INT | Spell DC 13, spell attack +5" % pb,
        "Spell slots: %d/%d first-level" % (ch["spell_slots"].get("1", 0),
                                            ch["spell_slots_max"].get("1", 0)),
        "Infusions: %s" % ", ".join(ch["infusions_known"]),
        "Skills: %s" % ", ".join(
            "%s %+.d" % (s.title(), _skill_bonus(st, s))
            for s in ARTIFICER_SKILL_PROFS),
    ]
    if ch["conditions"]:
        lines.append("Conditions: %s" % ", ".join(ch["conditions"]))
    # flavor gear from the inventory system
    if qm is not None:
        try:
            lines.append("---")
            lines.append(qm.inventory_text())
        except Exception:
            pass
    return "\n".join(lines)


# -------------------------------------------------- combat tools ---

@function_tool(
    name="start_combat",
    description=("Start D&D combat. enemies: comma-separated 'name,hp,ac' "
                "triples, e.g. 'goblin,7,15; orc,15,13'. the player is added "
                "automatically with his AC and DEX."),
)
async def start_combat(enemies: str) -> str:
    st = _load()
    ch = _char(st)
    order = [_new_combatant("the player", ch["hp"], ch["ac"],
                           dex_mod=_mod_for(st, "DEX"))]
    for part in (enemies or "").split(";"):
        bits = [b.strip() for b in part.split(",")]
        if len(bits) == 3:
            try:
                order.append(_new_combatant(bits[0], int(bits[1]),
                                           int(bits[2]), is_enemy=True))
            except ValueError:
                pass
    st["combat"] = {"round": 1, "order": order, "turn": 0}
    _save(st)
    return ("Combat begins! %d combatants. Roll initiative with "
            "roll_initiative." % len(order))


@function_tool(
    name="roll_initiative",
    description="Roll initiative for everyone in the current D&D combat and "
                "sort turn order.",
)
async def roll_initiative() -> str:
    st = _load()
    c = st["combat"]
    if not c:
        return "No combat running."
    for m in c["order"]:
        m["initiative"] = _d(20) + m.get("dex_mod", 0)
    c["order"].sort(key=lambda m: m["initiative"], reverse=True)
    c["turn"] = 0
    _save(st)
    lines = ["Initiative!"]
    for m in c["order"]:
        lines.append("- %s: %d" % (m["name"], m["initiative"]))
    return "\n".join(lines)


@function_tool(
    name="next_turn",
    description="Advance to the next turn in D&D combat.",
)
async def next_turn() -> str:
    st = _load()
    c = st["combat"]
    if not c:
        return "No combat running."
    c["turn"] = (c["turn"] + 1) % len(c["order"])
    if c["turn"] == 0:
        c["round"] += 1
    cur = c["order"][c["turn"]]
    # boss phase checks
    _save(st)
    extra = ""
    for key, b in BOSSES.items():
        if cur["name"] == b["title"]:
            for threshold, text in b["phases"]:
                if cur["hp"] <= threshold and cur["hp"] > 0:
                    if text not in cur.get("phases_shown", []):
                        cur.setdefault("phases_shown", []).append(text)
                        extra = "\n*** %s ***" % text
                        _save(st)
    return "Round %d - %s's turn (%d/%d HP).%s" % (
        c["round"], cur["name"], max(cur["hp"], 0), cur["max_hp"], extra)


@function_tool(
    name="combat_status",
    description="Show the current D&D combat: round, turn order, HP, "
                "conditions.",
)
async def combat_status() -> str:
    return _combat_text(_load())


@function_tool(
    name="end_combat",
    description="End D&D combat. victory=true awards XP to the player's D&D XP "
                "pool.",
)
async def end_combat(victory: bool = True) -> str:
    st = _load()
    if not st["combat"]:
        return "No combat running."
    st["combat"] = None
    if victory:
        st["character"]["xp_dnd"] += 100
        _save(st)
        return "Victory! +100 D&D XP (total %d)." % st["character"]["xp_dnd"]
    _save(st)
    return "Combat ends. The party retreats to fight another day."


@function_tool(
    name="summon_boss",
    description=("Face one of the player's real-life bosses in D&D: 'the static' "
                "(GitHub push), 'the veilwarden' (paranormal research), or "
                "'babel' (translation layer). Starts combat with the boss."),
)
async def summon_boss(boss_name: str) -> str:
    st = _load()
    key = (boss_name or "").lower().strip()
    if key not in BOSSES:
        return "Bosses: the static, the veilwarden, babel."
    b = BOSSES[key]
    ch = _char(st)
    order = [_new_combatant("the player", ch["hp"], ch["ac"],
                           dex_mod=_mod_for(st, "DEX")),
             _boss_combatant(key)]
    st["combat"] = {"round": 1, "order": order, "turn": 0}
    _save(st)
    return ("*** BOSS FIGHT ***\n%s\n%s\n\nAC %d, HP %d. %s\n\n"
            "Roll initiative!" % (
                b["title"], b["flavor"], b["ac"], b["hp"], b["type"]))


@function_tool(
    name="boss_info",
    description=("Read a boss stat block: 'the static', 'the veilwarden', "
                "or 'babel'."),
)
async def boss_info(boss_name: str) -> str:
    key = (boss_name or "").lower().strip()
    if key not in BOSSES:
        return "Bosses: the static, the veilwarden, babel."
    b = BOSSES[key]
    lines = ["%s (%s)" % (b["title"], b["type"]),
             b["flavor"],
             "AC %d | HP %d | %s" % (b["ac"], b["hp"], b["speed"]),
             " ".join("%s %d (%+d)" % (a, v, ability_mod(v))
                      for a, v in b["scores"].items())]
    for a in b["attacks"]:
        if "to_hit" in a:
            lines.append("- %s: +%d to hit, %s %s" % (
                a["name"], a["to_hit"], a["dmg"], a["dtype"]))
        else:
            lines.append("- %s: DC %d %s save, %s %s, %s" % (
                a["name"], a["dc"], a["save"], a["dmg"], a["dtype"],
                a["effect"]))
    lines.append("Loot: %s" % "; ".join(b["loot"]))
    return "\n".join(lines)


# -------------------------------------------------- quests/dungeon ---

@function_tool(
    name="quest_board",
    description="Show the player's real-life quests as D&D quest entries: the "
                "Dragon's Hoard, the Polyglot Engine, the Five Tales, and "
                "the boss quests.",
)
async def quest_board() -> str:
    return _quest_text(_load())


@function_tool(
    name="delve_dungeon",
    description=("Generate a quick D&D dungeon break: rooms with SRD "
                "monsters, traps, and treasure. Say 'delve' when the player "
                "wants a short dungeon run between real work."),
)
async def delve_dungeon() -> str:
    st = _load()
    d = _gen_dungeon(depth=3)
    st["dungeon"] = d
    _save(st)
    lines = ["You descend. %d rooms ahead." % d["depth"]]
    r = d["rooms"][0]
    lines.append(_room_text(r))
    return "\n".join(lines)


def _room_text(r):
    if r["kind"] == "monster":
        m = r["what"]
        return ("Room %d: a %s snarls! (AC %d, HP %d). "
                "Start combat or attack." % (r["n"], m["name"], m["ac"],
                                             m["hp"]))
    if r["kind"] == "trap":
        t = r["what"]
        return ("Room %d: you spot %s. DC %d %s save or take %s %s." % (
            r["n"], t["name"], t["dc"], t["save"], t["dmg"], t["dtype"]))
    if r["kind"] == "treasure":
        return "Room %d: treasure! %s." % (r["n"], r["what"])
    if r["kind"] == "boss":
        m = r["what"]
        return ("Room %d - BOSS ROOM: a mighty %s blocks the way! "
                "(AC %d, HP %d)." % (r["n"], m["name"], m["ac"], m["hp"]))
    return "Room %d: %s." % (r["n"], r["what"])


@function_tool(
    name="dungeon_next",
    description="Move to the next room in the current dungeon delve.",
)
async def dungeon_next() -> str:
    st = _load()
    d = st.get("dungeon")
    if not d:
        return "No dungeon running. Say 'delve' to start one."
    d["at"] += 1
    if d["at"] >= len(d["rooms"]):
        st["dungeon"] = None
        _save(st)
        return "The dungeon is cleared! You climb back into the daylight."
    r = d["rooms"][d["at"]]
    _save(st)
    return _room_text(r)


@function_tool(
    name="claim_loot",
    description=("Claim treasure from a cleared dungeon room. Awards gold or "
                "a magic item to the player's inventory."),
)
async def claim_loot() -> str:
    st = _load()
    d = st.get("dungeon")
    if not d or d["at"] >= len(d["rooms"]):
        return "No treasure room to claim."
    r = d["rooms"][d["at"]]
    if r["kind"] != "treasure":
        return "This room holds no treasure."
    loot = r["what"]
    r["kind"] = "empty"
    r["what"] = "an empty chest"
    _save(st)
    if qm is not None and "potion" in loot.lower():
        qm.award_item(loot, "item", "heals 2d4+2",
                      "Looted from the dungeon depths.")
    elif qm is not None and "gp" in loot.lower():
        pass  # gold is flavor-tracked in the message
    msg = "Claimed: %s." % loot
    if secrets.randbelow(100) < 25:
        rare = secrets.choice(LOOT_RARE)
        if qm is not None:
            qm.award_item(rare, "item", "", "Rare dungeon find.")
        msg += " And something rarer glints beneath: %s!" % rare
    return msg


@function_tool(
    name="dnd_help",
    description="List the player's D&D voice commands for the game engine.",
)
async def dnd_help() -> str:
    return (
        "Rolls: 'roll perception' / 'roll arcana' (roll_check), "
        "'save dex' (roll_save).\n"
        "Fighting: 'I attack with my wrench' (attack_roll), "
        "'cast cure wounds' (cast_spell).\n"
        "Survival: 'I take 8 damage' (take_damage), 'I heal 5' (heal), "
        "'short rest' / 'long rest'.\n"
        "Character: 'show my character' (show_character), "
        "'show my inventory' (show_inventory).\n"
        "Combat: 'start combat', 'roll initiative', 'next turn', "
        "'combat status', 'end combat'.\n"
        "Bosses: 'face the static' / 'the veilwarden' / 'babel' "
        "(summon_boss), 'boss info'.\n"
        "Quests: 'quest board' (real work as D&D quests).\n"
        "Breaks: 'delve' for a quick dungeon, 'next room', 'claim loot'.")
