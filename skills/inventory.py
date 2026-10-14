"""Inventory / weapons / spells voice tools for Vagar's D&D layer.

Flavor only — nothing here has real-world effects. The quest reward hook
lives in quest_manager.award_item(): call it when a quest completes and
the new gear lands in the player's inventory automatically.
"""

from livekit.agents.llm import function_tool

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import quest_manager as qm


@function_tool(
    name="show_inventory",
    description=(
        "Show the player's character sheet: Artificer class and level, weapons "
        "with damage dice, magic items, and known spells. Use when he asks "
        "about his inventory, weapons, spells, gear, or character."
    ),
)
async def show_inventory() -> str:
    try:
        char = qm.get_character()
        char_name = char.get("name", "Player")
        lines = [
            "%s — Level %d %s." % (char_name, char.get("level", 3),
                                      char.get("class", "Artificer")),
        ]
        weapons = char.get("weapons", [])
        if weapons:
            lines.append("Weapons:")
            for w in weapons:
                lines.append("  - %s%s%s" % (
                    w.get("name"),
                    " (%s)" % w["detail"] if w.get("detail") else "",
                    " — %s" % w["flavor"] if w.get("flavor") else "",
                ))
        items = char.get("items", [])
        if items:
            lines.append("Magic items:")
            for i in items:
                lines.append("  - %s%s" % (
                    i.get("name"),
                    " — %s" % i["flavor"] if i.get("flavor") else "",
                ))
        spells = char.get("spells", [])
        if spells:
            lines.append("Spells:")
            for s in spells:
                lines.append("  - %s%s%s" % (
                    s.get("name"),
                    " (%s)" % s["detail"] if s.get("detail") else "",
                    " — %s" % s["flavor"] if s.get("flavor") else "",
                ))
        return "\n".join(lines)
    except Exception as e:
        return "Could not read the inventory: %s" % e


@function_tool(
    name="award_item",
    description=(
        "Award the player a new weapon, magic item, or spell as a quest reward. "
        "kind must be 'weapon', 'item', or 'spell'. detail is damage dice "
        "for weapons (e.g. '1d8 bludgeoning') or spell level (e.g. "
        "'cantrip', '1st-level'). flavor is a one-line origin story."
    ),
)
async def award_item(name: str, kind: str, detail: str = "",
                     flavor: str = "") -> str:
    try:
        if qm.award_item(name, kind, detail, flavor):
            return "%s added to the player's inventory." % name
        return "Already owned: %s." % name
    except ValueError as e:
        return str(e)
    except Exception as e:
        return "Could not award the item: %s" % e


@function_tool(
    name="cast_spell",
    description=(
        "Cast one of the player's known spells. Pure flavor — a spoken line, "
        "no real-world effect. Use when he asks Vagar to cast a spell."
    ),
)
async def cast_spell(name: str) -> str:
    try:
        return qm.cast_spell(name)
    except Exception as e:
        return "The spell fizzles: %s" % e
