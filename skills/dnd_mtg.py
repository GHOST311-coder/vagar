"""D&D 5e + Magic: The Gathering local knowledge base.

Voice tools backed by a local sqlite FTS5 index (no network, no cost):
  search_dnd_rules  - SRD 5.1 spells, monsters, and game mechanics
  search_mtg_rules  - MTG Comprehensive Rules (numbered rules + glossary)
  lookup_mtg_card   - card oracle text and stats

The index lives at vagar/knowledge/dnd_mtg/kb.sqlite and is built by
knowledge/dnd_mtg/build_kb.py from freely available sources (see
knowledge/dnd_mtg/SOURCES.md). Rules and oracle text only: no adventures,
no card art, no flavor text.
"""
try:
    from livekit.agents.llm import function_tool
except ImportError:  # pragma: no cover - allows unit testing off-laptop
    def function_tool(*_a, **_k):
        def _deco(f):
            return f
        return _deco

import os
import re
import sqlite3

DB_PATH = os.path.normpath(os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "..", "knowledge", "dnd_mtg", "kb.sqlite"))

MAX_EXCERPT = 600


def _connect():
    if not os.path.isfile(DB_PATH):
        return None
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    return con


def _toks(query):
    toks = re.findall(r"[A-Za-z0-9']+", query or "")
    return [t for t in toks if len(t) > 1 or t.isdigit()][:8]


def _match(query):
    toks = _toks(query)
    if not toks:
        return None
    return " ".join('"%s"' % t for t in toks)


OR_STOPWORDS = set(
    "a an the and or but if then else when what what how why who whom whose "
    "which does do did done is are was were be been being have has had having "
    "will would shall should can could may might must in on at to of for "
    "with by from as into over under between through during about against "
    "it its this that these those there here than too very just work works "
    "doesnt dont".split())


def _match_or(query):
    toks = [t for t in _toks(query)
            if t.lower() not in OR_STOPWORDS and len(t) > 2]
    if not toks:
        toks = _toks(query)
    if not toks:
        return None
    return " OR ".join('"%s"' % t for t in toks)


def _fts(con, table, select, mq, or_mq, limit):
    """FTS5 search with AND first, OR fallback for natural-language queries."""
    q = ("SELECT %s FROM %s WHERE %s MATCH ? "
         "ORDER BY bm25(%s) LIMIT ?") % (select, table, table, table)
    rows = con.execute(q, (mq, limit)).fetchall()
    if not rows and or_mq:
        rows = con.execute(q, (or_mq, limit)).fetchall()
    return rows


def _clip(text, n=MAX_EXCERPT):
    text = re.sub(r"\s+", " ", (text or "").strip())
    return text if len(text) <= n else text[:n].rsplit(" ", 1)[0] + "..."


@function_tool(
    name="search_dnd_rules",
    description=("Search the local D&D 5th edition rules (SRD 5.1): spells, "
                "monsters, and game mechanics. Use when the user asks how a "
                "spell works, what a monster does, or how a combat or "
                "exploration rule works."),
)
async def search_dnd_rules(query: str) -> str:
    con = _connect()
    if con is None:
        return "The D&D knowledge base is not built yet."
    try:
        q = (query or "").strip()
        mq = _match(q)
        if not mq:
            return "What D&D rule should I look up?"
        out = []
        row = con.execute(
            "SELECT name, text FROM dnd_spells WHERE lower(name)=lower(?)",
            (q,)).fetchone()
        if row:
            out.append("**%s** (D&D SRD 5.1, spell)\n%s"
                       % (row["name"], _clip(row["text"])))
        else:
            for r in con.execute(
                    "SELECT name, text FROM dnd_spells "
                    "WHERE dnd_spells MATCH '{name} : ' || ? "
                    "ORDER BY bm25(dnd_spells) LIMIT 1", (mq,)):
                out.append("**%s** (D&D SRD 5.1, spell)\n%s"
                           % (r["name"], _clip(r["text"])))
        row = con.execute(
            "SELECT name, text FROM dnd_monsters WHERE lower(name)=lower(?)",
            (q,)).fetchone()
        if row and len(out) < 3:
            out.append("**%s** (D&D SRD 5.1, monster)\n%s"
                       % (row["name"], _clip(row["text"])))
        if len(out) < 3:
            for r in _fts(con, "dnd_rules", "section, text", mq,
                          _match_or(q), 3 - len(out)):
                out.append("(D&D SRD 5.1, %s)\n%s"
                           % (r["section"], _clip(r["text"])))
        if not out:
            return "No D&D rule found for '%s' in the local SRD." % q
        return "\n\n".join(out)
    except Exception as e:
        return "D&D lookup failed: %s" % e
    finally:
        con.close()


@function_tool(
    name="search_mtg_rules",
    description=("Search the local Magic: The Gathering Comprehensive Rules, "
                "including the glossary and Commander (section 903) rules. "
                "Use when the user asks how an MTG mechanic, keyword, or "
                "format rule works. A bare rule number like '903.4' looks it "
                "up directly."),
)
async def search_mtg_rules(query: str) -> str:
    con = _connect()
    if con is None:
        return "The MTG rules knowledge base is not built yet."
    try:
        q = (query or "").strip()
        if not q:
            return "What MTG rule should I look up?"
        out = []
        if re.fullmatch(r"\d{3}(\.\d+[a-z]?)?", q):
            row = con.execute(
                "SELECT num, text FROM mtg_rules WHERE num=?", (q,)).fetchone()
            if row:
                return "**%s** (MTG Comprehensive Rules)\n%s" % (
                    row["num"], _clip(row["text"]))
            return "No MTG rule numbered %s." % q
        row = con.execute(
            "SELECT num, text FROM mtg_rules WHERE num=?",
            ("G:" + q.title(),)).fetchone()
        if row:
            out.append("**%s** (MTG glossary)\n%s"
                       % (row["num"][2:], _clip(row["text"])))
        mq = _match(q)
        if mq:
            # dedupe the glossary exact-hit against FTS hits below
            seen_nums = set()
            for o in out:
                m2 = re.match(r"\*\*(.+?)\*\*", o)
                if m2:
                    seen_nums.add(m2.group(1))
            for r in _fts(con, "mtg_rules", "num, text", mq,
                          _match_or(q), 3 - len(out)):
                label = ("MTG glossary, " + r["num"][2:]
                         if r["num"].startswith("G:")
                         else "MTG Comprehensive Rules " + r["num"])
                key = r["num"][2:] if r["num"].startswith("G:") else r["num"]
                if key in seen_nums:
                    continue
                seen_nums.add(key)
                out.append("**%s**\n%s" % (label, _clip(r["text"])))
        if not out:
            return "No MTG rule found for '%s' locally." % q
        return "\n\n".join(out)
    except Exception as e:
        return "MTG rules lookup failed: %s" % e
    finally:
        con.close()


@function_tool(
    name="lookup_mtg_card",
    description=("Look up a Magic: The Gathering card by name from the local "
                "oracle database. Returns mana cost, type line, rules text, "
                "and power/toughness. Use when the user asks what a card does "
                "or names a card."),
)
async def lookup_mtg_card(card_name: str) -> str:
    con = _connect()
    if con is None:
        return "The MTG card database is not built yet."
    try:
        q = (card_name or "").strip()
        if not q:
            return "Which card should I look up?"
        row = con.execute(
            "SELECT * FROM mtg_card_detail WHERE lower(name)=lower(?)",
            (q,)).fetchone()
        if row is None:
            rows = con.execute(
                "SELECT name FROM mtg_card_detail WHERE lower(name) LIKE ? "
                "LIMIT 6", (q.lower() + "%",)).fetchall()
            if len(rows) == 1:
                row = con.execute(
                    "SELECT * FROM mtg_card_detail WHERE name=?",
                    (rows[0]["name"],)).fetchone()
            elif len(rows) > 1:
                return ("Multiple cards start with '%s': %s. "
                        "Which one did you mean?"
                        % (q, ", ".join(r["name"] for r in rows)))
        if row is None:
            mq = _match(q)
            if mq:
                rows = con.execute(
                    "SELECT name FROM mtg_cards WHERE mtg_cards MATCH "
                    "'{name} : ' || ? ORDER BY bm25(mtg_cards) LIMIT 5",
                    (mq,)).fetchall()
                if rows:
                    return ("No exact match for '%s'. Did you mean: %s?"
                            % (q, ", ".join(r["name"] for r in rows)))
            return "No MTG card found named '%s'." % q
        pt = ""
        if row["power"] or row["toughness"]:
            pt = "  %s/%s" % (row["power"], row["toughness"])
        elif row["loyalty"]:
            pt = "  loyalty %s" % row["loyalty"]
        return ("**%s** — %s\n%s\n%s\n(oracle text via Scryfall)"
                % (row["name"], row["mana_cost"],
                   row["type_line"] + pt, _clip(row["oracle_text"], 700)))
    except Exception as e:
        return "Card lookup failed: %s" % e
    finally:
        con.close()
