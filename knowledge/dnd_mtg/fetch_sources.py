"""Fetch the D&D / MTG knowledge sources and build the local search index.

Downloads (all free, ~30 MB total):
  - D&D 5e SRD 5.1 PDF (Wizards of the Coast, CC BY 4.0)
  - MTG Comprehensive Rules text (Wizards of the Coast, freely published)
  - Scryfall oracle-cards bulk data (oracle text only, no art)

Then builds kb.sqlite (FTS5 full-text index) via build_kb.py.

Usage:
    python fetch_sources.py

The index lands in this directory (knowledge/dnd_mtg/kb.sqlite) and the
dnd_mtg skill picks it up automatically. Re-run any time to refresh.
Requires: pypdf (installed automatically if missing).
"""
import json
import os
import subprocess
import sys
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
RAW = os.path.join(HERE, "raw")

SRD_URL = "https://media.wizards.com/2016/downloads/DND/SRD-OGL_V5.1.pdf"
COMPRULES_URL = ("https://media.wizards.com/2026/downloads/"
                 "MagicCompRules%2020260925.txt")
SCRYFALL_BULK_API = "https://api.scryfall.com/bulk-data"

UA = {"User-Agent": "VagarKnowledgeFetch/1.0 (personal local knowledge base)"}


def download(url, dest):
    if os.path.isfile(dest) and os.path.getsize(dest) > 0:
        print("exists, skipping: %s" % os.path.basename(dest))
        return
    print("downloading %s ..." % os.path.basename(dest), flush=True)
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=120) as r, \
            open(dest, "wb") as f:
        while True:
            chunk = r.read(1024 * 256)
            if not chunk:
                break
            f.write(chunk)
    print("  saved %d bytes" % os.path.getsize(dest))


def scryfall_oracle_url():
    req = urllib.request.Request(SCRYFALL_BULK_API, headers=UA)
    with urllib.request.urlopen(req, timeout=60) as r:
        data = json.load(r)
    for b in data["data"]:
        if b.get("type") == "oracle_cards":
            return b["jsonl_download_uri"]
    raise RuntimeError("oracle_cards bulk not found in Scryfall API")


def main():
    os.makedirs(RAW, exist_ok=True)
    try:
        import pypdf  # noqa: F401
    except ImportError:
        print("installing pypdf (build-time dependency)...", flush=True)
        subprocess.check_call(
            [sys.executable, "-m", "pip", "install", "pypdf"])
    download(SRD_URL, os.path.join(RAW, "SRD-5.1.pdf"))
    download(COMPRULES_URL, os.path.join(RAW, "MagicCompRules.txt"))
    download(scryfall_oracle_url(),
             os.path.join(RAW, "oracle-cards.jsonl.gz"))
    print("building search index...", flush=True)
    env = dict(os.environ)
    env["VAGAR_KB_DIR"] = HERE
    subprocess.check_call([sys.executable,
                           os.path.join(HERE, "build_kb.py")], env=env)
    print("done. Index at: %s" % os.path.join(HERE, "kb.sqlite"))


if __name__ == "__main__":
    main()
