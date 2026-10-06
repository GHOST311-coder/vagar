# Sources — D&D / MTG knowledge base

Local personal reference only. Rules and oracle text; no adventures,
no card art, no flavor text.

## 1. D&D 5th Edition SRD 5.1
- File: `raw/SRD-5.1.pdf`
- Origin: Wizards of the Coast official media server
  (https://media.wizards.com/2016/downloads/DND/SRD-OGL_V5.1.pdf)
- License: Systems Reference Document 5.1, (c) Wizards of the Coast LLC.
  Released under **Creative Commons Attribution 4.0 International (CC BY 4.0)**
  per Wizards of the Coast's 2023 announcement. Attribution retained here and
  in query citations ("D&D SRD 5.1").
- Content used: rules text only — classes, spells, monsters, mechanics.

## 2. Magic: The Gathering Comprehensive Rules
- File: `raw/MagicCompRules.txt` (effective 2026-09-25)
- Origin: Wizards of the Coast official rules page
  (https://magic.wizards.com/en/rules)
- License: (c) Wizards of the Coast LLC. The Comprehensive Rules are published
  freely by WotC for reference. Used here as a local personal reference;
  citations read "MTG Comprehensive Rules".
- Content used: numbered rules, section headers, and glossary (includes the
  Commander format rules, section 903).

## 3. MTG card oracle text
- File: `raw/oracle-cards.jsonl.gz` (bulk snapshot 2026-10-06)
- Origin: Scryfall bulk data API (https://api.scryfall.com/bulk-data),
  "Oracle Cards" set (one record per unique oracle ID, no imagery).
- License/terms: data provided free by Scryfall for this kind of use; all
  card text (c) Wizards of the Coast LLC. Local personal reference only.
  Citations read "oracle text via Scryfall".
- Content used: card name, mana cost, type line, oracle text, power/toughness/
  loyalty. Tokens, emblems, and art cards excluded. Flavor text not stored.

## Build
Run `build_kb.py` (requires pypdf, build-time only) to produce `kb.sqlite`
(FTS5 full-text index), or `fetch_sources.py` to download sources and build
in one step. Re-run any time to refresh from newer sources.
