"""Build the local D&D / MTG knowledge base.

Reads the downloaded sources in raw/ and builds kb.sqlite with FTS5 tables:
  dnd_spells(name, text)      - parsed SRD 5.1 spell entries
  dnd_monsters(name, text)    - parsed SRD 5.1 monster stat blocks
  dnd_rules(section, text)    - SRD rules text, paragraph-level chunks
  mtg_rules(num, text)        - Comprehensive Rules numbered rules + glossary
  mtg_cards(name, type_line, oracle_text) + mtg_card_detail(...)

Sources (see SOURCES.md):
  SRD-5.1.pdf            - D&D 5e SRD 5.1, (c) Wizards of the Coast, CC BY 4.0
  MagicCompRules.txt     - MTG Comprehensive Rules, (c) Wizards of the Coast
  oracle-cards.jsonl.gz  - Scryfall bulk oracle cards (no art, oracle text only)

BASE defaults to the live laptop path; override with VAGAR_KB_DIR env var
(the public repo's fetch script points it at a repo-relative directory).
Requires: pypdf (build-time only).
"""
import os
import re
import sys
import json
import gzip
import sqlite3
import datetime

# Default: the directory this script lives in (works for both the live install
# at vagar/knowledge/dnd_mtg/ and a repo-relative public copy). Override with
# VAGAR_KB_DIR to point it elsewhere.
BASE = os.environ.get(
    "VAGAR_KB_DIR", os.path.dirname(os.path.abspath(__file__)))
RAW = os.path.join(BASE, "raw")
DB = os.path.join(BASE, "kb.sqlite")

DASH = "[\u2010\u2011\u2012\u2013\u2014\u2212\u00ad]"
PG = "\n\x00PG\x00\n"  # page-boundary marker (lets us fix split words)

STOPWORDS = set(
    "a an as at be by do go he in is it me my no of on or so to up us we "
    "the and are for his her him its not our she was you with that this "
    "from have were will would their there what when which who than then "
    "them into over such only also".split())


def clean_srd(t):
    t = t.replace("\t\r \ufffd", " ").replace("\t\r\ufffd", " ")
    t = t.replace("\t", " ").replace("\r", " ")
    t = re.sub(r"(?<=[A-Za-z])\ufffd(?=[A-Za-z])", "'", t)
    t = t.replace("\ufffd", "")
    t = re.sub(DASH, "-", t)
    t = re.sub(r"-{2,}", "-", t)
    t = re.sub(r"[ \u00a0]+", " ", t)
    t = re.sub(r" *\n *", "\n", t)
    t = re.sub(r"\n{3,}", "\n\n", t)
    return t.strip()


SPELL_RE = re.compile(
    r"^([A-Z][A-Za-z'’\-/ ]{1,45})\n"
    r"((?:\d+(?:st|nd|rd|th)-level\s+[A-Za-z]+(?:\s*\(ritual\))?"
    r"|[A-Za-z]+\s+cantrip))\s*$",
    re.MULTILINE)

MON_RE = re.compile(
    r"^([A-Z][A-Za-z'’\-/() ]{2,50})\n"
    r"(Small|Medium|Large|Tiny|Huge|Gargantuan)\s+"
    r"(aberration|beast|celestial|construct|dragon|elemental|fey|fiend|giant|"
    r"humanoid|monstrosity|ooze|plant|undead)\b",
    re.MULTILINE)

RULE_RE = re.compile(r"^(\d{3}(?:\.\d+[a-z]?)?)\.\s+(.*)$")


def fix_page_splits(t):
    """Rejoin words split across a page boundary (marked with PG).

    Joins only when both fragments are short and the tail is not a common
    word, e.g. 'tu'+'rn' -> 'turn' but 'that'+'is' stays split.
    """
    def rep(m):
        a, b = m.group(1), m.group(2)
        if b.lower() in STOPWORDS:
            return a + "\n" + b
        return a + b
    t = re.sub(r"([A-Za-z]{1,4})-\n\x00PG\x00\n([a-z]{1,4})",
               lambda m: m.group(1) + m.group(2), t)
    t = re.sub(r"([A-Za-z]{1,4})\n\x00PG\x00\n([a-z]{1,4})", rep, t)
    return t.replace(PG, "\n")


def parse_srd():
    import pypdf
    pdf_path = os.path.join(RAW, "SRD-5.1.pdf")
    reader = pypdf.PdfReader(pdf_path)
    pages = []
    for p in reader.pages:
        t = clean_srd(p.extract_text() or "")
        t = re.sub(r"Not for resale\. Permission granted to print or "
                   r"photocopy this document for personal use only\.", "", t)
        t = re.sub(r"System Reference Document 5\.1\s*\d*", "", t)
        pages.append(t.strip())
    full = PG.join(pages)

    # find all entry headers (spells + monsters), sorted by position
    headers = []
    for m in SPELL_RE.finditer(full):
        headers.append((m.start(), "spell", m.group(1).strip(), m))
    for m in MON_RE.finditer(full):
        headers.append((m.start(), "monster", m.group(1).strip(), m))
    headers.sort(key=lambda h: h[0])

    spells, monsters, spans = [], [], []
    for idx, (pos, kind, name, m) in enumerate(headers):
        end = headers[idx + 1][0] if idx + 1 < len(headers) else len(full)
        text = fix_page_splits(full[pos:end]).strip()
        text = re.sub(r"\n{3,}", "\n\n", text)
        if kind == "spell":
            spells.append((name, text))
        else:
            monsters.append((name, text))
        spans.append((pos, end))

    # rules: mask out entry spans, then chunk per paragraph (finer FTS hits)
    masked = list(full)
    for s, e in spans:
        for i in range(s, e):
            masked[i] = " "
    masked = "".join(masked)
    rules = []
    for pageno, page in enumerate(masked.split(PG), start=1):
        page = page.replace("\x00", " ").strip()
        if len(page) < 300:
            continue
        heading = "SRD 5.1"
        for line in page.split("\n"):
            ls = line.strip()
            if 3 <= len(ls) <= 60 and re.fullmatch(
                    r"[A-Z][A-Z0-9 '\-,&()!:]*", ls):
                heading = ls.title()
                break
        section = "%s (p. %d)" % (heading, pageno)
        # sentence-aware chunks ~450 chars (PDF wraps lines mid-sentence,
        # so newline-based paragraphs are unreliable)
        text = re.sub(r"\s+", " ", page)
        sents = re.split(r"(?<=[.!?])\s+(?=[A-Z0-9])", text)
        buf = ""
        for s in sents:
            s = s.strip()
            if not s:
                continue
            if buf and len(buf) + len(s) + 1 > 450:
                if len(buf) >= 80:
                    rules.append((section, buf.strip(), pageno))
                buf = s
            else:
                buf = (buf + " " + s).strip() if buf else s
        if len(buf) >= 80:
            rules.append((section, buf.strip(), pageno))
    return spells, monsters, rules


def parse_comp_rules():
    path = os.path.join(RAW, "MagicCompRules.txt")
    lines = open(path, encoding="utf-8", errors="replace").read().splitlines()
    gidx = max(i for i, l in enumerate(lines) if l.strip() == "Glossary")

    def norm(i):
        return lines[i].strip().strip("\xa0")

    # Body starts at the first subrule (the Contents only lists section
    # headers, never subrules); walk back to include section headers.
    sub = next(i for i in range(len(lines))
               if re.match(r"^\d{3}\.\d+[a-z]?\.\s+", norm(i)))
    start = sub
    while start > 0:
        prev = norm(start - 1)
        if prev == "" or re.match(r"^\d+\.\s+\S", prev):
            start -= 1
        else:
            break

    rules = []
    cur = None
    for i in range(start, gidx):
        s = norm(i)
        if not s:
            continue
        m = RULE_RE.match(s)
        if m:
            if cur:
                rules.append(tuple(cur))
            cur = [m.group(1), m.group(2)]
        elif cur:
            cur[1] += " " + s
    if cur:
        rules.append(tuple(cur))

    gloss = []
    term, defn = None, []
    for l in lines[gidx + 1:]:
        s = l.strip().strip("\xa0")
        if not s:
            if term:
                gloss.append((term, " ".join(defn)))
                term, defn = None, []
            continue
        if term is None:
            term, defn = s, []
        else:
            defn.append(s)
    if term:
        gloss.append((term, " ".join(defn)))
    return rules, gloss


def parse_cards():
    cards = {}
    path = os.path.join(RAW, "oracle-cards.jsonl.gz")
    with gzip.open(path, "rt", encoding="utf-8") as f:
        for line in f:
            c = json.loads(line)
            if c.get("layout") in ("token", "double_faced_token", "emblem",
                                   "art_series"):
                continue
            oracle = c.get("oracle_text") or ""
            if not oracle and c.get("card_faces"):
                oracle = " // ".join(
                    fx.get("oracle_text", "") for fx in c["card_faces"])
            name = c.get("name", "")
            entry = (
                name,
                c.get("mana_cost", "") or "",
                c.get("type_line", "") or "",
                oracle,
                c.get("power") or "",
                c.get("toughness") or "",
                c.get("loyalty") or "",
            )
            # a few oracle IDs share a name; keep the fullest entry
            if name in cards:
                if len(oracle) > len(cards[name][3]):
                    cards[name] = entry
            else:
                cards[name] = entry
    return list(cards.values())


def build():
    os.makedirs(BASE, exist_ok=True)
    if os.path.isfile(DB):
        os.remove(DB)
    con = sqlite3.connect(DB)
    try:
        con.execute("CREATE VIRTUAL TABLE fts_probe USING fts5(x)")
        con.execute("DROP TABLE fts_probe")
    except sqlite3.OperationalError:
        sys.exit("ERROR: this sqlite build lacks FTS5")
    con.execute("CREATE VIRTUAL TABLE dnd_spells USING fts5(name, text, tokenize='porter')")
    con.execute("CREATE VIRTUAL TABLE dnd_monsters USING fts5(name, text, tokenize='porter')")
    con.execute("CREATE VIRTUAL TABLE dnd_rules USING fts5(section, text, tokenize='porter')")
    con.execute("CREATE VIRTUAL TABLE mtg_rules USING fts5(num, text, tokenize='porter')")
    con.execute("CREATE VIRTUAL TABLE mtg_cards USING fts5(name, type_line, oracle_text, tokenize='porter')")
    con.execute("""CREATE TABLE mtg_card_detail(
        name TEXT PRIMARY KEY, mana_cost TEXT, type_line TEXT,
        oracle_text TEXT, power TEXT, toughness TEXT, loyalty TEXT)""")
    con.execute("CREATE TABLE meta(k TEXT PRIMARY KEY, v TEXT)")

    print("parsing SRD...", flush=True)
    spells, monsters, rules = parse_srd()
    print("  spells=%d monsters=%d rule-paragraphs=%d"
          % (len(spells), len(monsters), len(rules)))
    con.executemany("INSERT INTO dnd_spells(name, text) VALUES(?, ?)", spells)
    con.executemany("INSERT INTO dnd_monsters(name, text) VALUES(?, ?)", monsters)
    con.executemany("INSERT INTO dnd_rules(section, text) VALUES(?, ?)",
                    [(s, t) for s, t, _ in rules])

    print("parsing comp rules...", flush=True)
    crule, gloss = parse_comp_rules()
    print("  rules=%d glossary=%d" % (len(crule), len(gloss)))
    con.executemany("INSERT INTO mtg_rules(num, text) VALUES(?, ?)", crule)
    con.executemany("INSERT INTO mtg_rules(num, text) VALUES(?, ?)",
                    [("G:" + t, d) for t, d in gloss])

    print("parsing cards...", flush=True)
    cards = parse_cards()
    print("  cards=%d" % len(cards))
    con.executemany("INSERT INTO mtg_cards(name, type_line, oracle_text) VALUES(?, ?, ?)",
                    [(n, tl, ot) for n, _, tl, ot, _, _, _ in cards])
    con.executemany("INSERT INTO mtg_card_detail VALUES(?, ?, ?, ?, ?, ?, ?)", cards)

    con.execute("INSERT INTO meta VALUES('built_at', ?)",
                (datetime.datetime.now().isoformat(timespec="seconds"),))
    con.execute("INSERT INTO meta VALUES('sources', ?)",
                ("SRD-5.1.pdf (CC BY 4.0); MagicCompRules 2026-09-25 (WotC); "
                 "Scryfall oracle-cards bulk 2026-10-06 (no art)",))
    con.commit()
    size = os.path.getsize(DB)
    print("wrote %s (%d bytes)" % (DB, size))
    con.close()


if __name__ == "__main__":
    build()
