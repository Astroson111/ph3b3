import logging

log = logging.getLogger("ph3b3.search")

try:
    from duckduckgo_search import DDGS
    DDG_AVAILABLE = True
except ImportError:
    DDG_AVAILABLE = False
    log.warning("duckduckgo-search not installed")

class SearchModule:
    def __init__(self):
        self.available = DDG_AVAILABLE
        log.info("Search ready" if DDG_AVAILABLE else "Search unavailable")

    def search(self, query, max_results=5):
        if not self.available: return "Web search not available."
        try:
            with DDGS() as ddgs:
                results = list(ddgs.text(query, max_results=max_results))
            if not results: return f"No results for '{query}'"
            lines = [f"Search: {query}\n"]
            for i, r in enumerate(results, 1):
                lines.append(f"{i}. {r.get('title','')}")
                lines.append(f"   {r.get('body','')[:200]}")
                lines.append(f"   {r.get('href','')}\n")
            return "\n".join(lines)
        except Exception as e:
            return f"Search error: {e}"

    def news(self, query, max_results=5):
        if not self.available: return "Web search not available."
        try:
            with DDGS() as ddgs:
                results = list(ddgs.news(query, max_results=max_results))
            if not results: return f"No news for '{query}'"
            lines = [f"News: {query}\n"]
            for r in results:
                lines.append(f"[{r.get('date','')[:10]}] {r.get('title','')}")
                lines.append(f"  {r.get('body','')[:150]}\n")
            return "\n".join(lines)
        except Exception as e:
            return f"News error: {e}"
