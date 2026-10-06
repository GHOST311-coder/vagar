"""Web search: query DuckDuckGo's lite endpoint and return titles, snippets,
and URLs. Pairs with web_fetch (search first, then fetch the best result).

Guards: GET-only, 15s timeout, max 8 results, no credentials, no cookies.
The lite endpoint is used because the main html endpoint bot-walls
datacenter-style IPs. Returns short snippets so results fit the voice loop.
"""
from livekit.agents.llm import function_tool

import html as _html
import re as _re
import urllib.parse as _uparse
import urllib.request as _urequest

_TIMEOUT = 15
_MAX_RESULTS = 8
_UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}


def _clean(s):
    s = _re.sub(r"<[^>]+>", "", s or "")
    return _html.unescape(s).strip()


@function_tool(
    name="web_search",
    description="Search the web for a topic and return titles, snippets, and URLs. Use for current facts, then use web_fetch on the best URL for details.",
)
async def web_search(query: str, n: int = 5) -> str:
    if not query or not isinstance(query, str):
        return "No query given."
    try:
        count = max(1, min(int(n), _MAX_RESULTS))
    except (TypeError, ValueError):
        count = 5
    try:
        url = "https://lite.duckduckgo.com/lite/?q=" + _uparse.quote(query.strip())
        req = _urequest.Request(url, headers=_UA)
        with _urequest.urlopen(req, timeout=_TIMEOUT) as resp:
            page = resp.read().decode("utf-8", errors="replace")
    except Exception as e:
        return "Search failed: %s" % e
    if "anomaly" in page[:3000].lower() or "challenge" in page[:3000].lower():
        return "Search blocked by a bot challenge; try again later."

    results = []
    # lite DDG: <a href="URL" ... class='result-link'>TITLE</a> then
    # <td class='result-snippet'>SNIPPET</td> (single quotes, href first)
    for m in _re.finditer(
        r'<a[^>]*href=[\'"]([^\'"]+)[\'"][^>]*class=[\'"]result-link[\'"][^>]*>(.*?)</a>',
        page, _re.S,
    ):
        href, title = m.group(1), _clean(m.group(2))
        # snippet: look ahead for the result-snippet cell before the next link
        tail = page[m.end():m.end() + 1500]
        snip = _re.search(
            r'class=[\'"]result-snippet[\'"][^>]*>(.*?)</td>',
            tail, _re.S,
        )
        snippet = _clean(snip.group(1)) if snip else ""
        if "duckduckgo.com/l/?uddg=" in href or href.startswith("//duckduckgo.com/l/?uddg="):
            href = _uparse.unquote(href.split("uddg=", 1)[1].split("&", 1)[0])
        if not href.startswith("http"):
            continue
        if "Sponsored" in title or not title:
            continue
        results.append((title, snippet, href))
        if len(results) >= count:
            break

    if not results:
        # fallback: any result-link anchors at all
        return "No results for: %s" % query

    lines = []
    for i, (title, snippet, href) in enumerate(results, 1):
        lines.append(
            "%d. %s\n   %s\n   %s"
            % (i, title[:120], snippet[:220], href[:200])
        )
    return "\n".join(lines)
