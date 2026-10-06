# D&D + MTG knowledge base

A local, offline, full-text searchable reference for Dungeons & Dragons
5th edition and Magic: The Gathering, backing Vagar's `dnd_mtg` skill
(`search_dnd_rules`, `search_mtg_rules`, `lookup_mtg_card`).

## Contents

| Table | Rows | What |
|---|---|---|
| `dnd_spells` | ~320 | SRD 5.1 spell entries (full text) |
| `dnd_monsters` | ~310 | SRD 5.1 monster stat blocks |
| `dnd_rules` | ~1k chunks | SRD rules text, sentence-chunked, with page citations |
| `mtg_rules` | ~1.3k + ~750 glossary | MTG Comprehensive Rules + glossary (incl. Commander §903) |
| `mtg_cards` / `mtg_card_detail` | ~35k | Card name, mana cost, type line, oracle text, P/T |

Rules and oracle text only — no adventures, no card art, no flavor text.

## Build it

```bash
python fetch_sources.py
```

Downloads ~30 MB of free sources, then builds `kb.sqlite` (~28 MB, FTS5).
Re-run any time to refresh from newer sources. The skill finds the index
automatically; no worker restart needed for data refreshes.

## Sources & attribution

- **D&D 5e SRD 5.1** — (c) Wizards of the Coast, released under
  **Creative Commons Attribution 4.0 (CC BY 4.0)**. Downloaded from WotC's
  official media server. Rules text only.
- **MTG Comprehensive Rules** — (c) Wizards of the Coast, published freely
  for reference.
- **Scryfall oracle-cards bulk** — free bulk data API; card text
  (c) Wizards of the Coast. Oracle text only, no imagery.

Downloaded source files are NOT committed to this repo (too large) —
`fetch_sources.py` retrieves them on setup.
