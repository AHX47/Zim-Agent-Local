"""
ZimAgent MCP Server
====================
Exposes ZIM file operations as MCP tools:

  zim_read_article(path)                  — get article text
  zim_search(query, max_results)          — full-text or prefix search
  zim_write_article(path, title, html)    — create / replace article
  zim_edit_article(path, new_html)        — edit existing article
  zim_delete_article(path)                — soft-delete article
  zim_restore_article(path)               — undo soft-delete
  zim_list_modified()                     — list overlay entries
  zim_list_articles(max)                  — list all overlay articles
  zim_stats()                             — archive statistics

Run::

    python -m zim_agent.mcp_server --zim data/wikipedia_en_mini.zim
    # or via stdio for Claude Desktop / LangChain:
    python -m zim_agent.mcp_server --zim data/... --transport stdio
"""

from __future__ import annotations

import json
import logging
from typing import Optional

logger = logging.getLogger(__name__)


def create_zim_mcp_server(zim_path: str, overlay_path: Optional[str] = None):
    """Build a FastMCP server with ZIM tools.

    Parameters
    ----------
    zim_path : str
        Path to the .zim file.
    overlay_path : str, optional
        SQLite overlay DB path.  Auto-derived from zim_path if None.
    """
    try:
        from fastmcp import FastMCP
    except ImportError:
        raise ImportError("fastmcp required: pip install fastmcp")

    from .zim_manager import ZimManager

    mcp = FastMCP("ZimAgent")

    # Shared manager (lazy open)
    _mgr: dict = {"manager": None}

    def get_mgr() -> ZimManager:
        if _mgr["manager"] is None:
            m = ZimManager(zim_path, overlay_path)
            m.open()
            _mgr["manager"] = m
        return _mgr["manager"]

    # ------------------------------------------------------------------
    # Tool: read
    # ------------------------------------------------------------------

    @mcp.tool()
    def zim_read_article(path: str) -> str:
        """Read an article from the ZIM archive by its URL path.

        Parameters
        ----------
        path : str   Article URL path, e.g. "A/Python_(programming_language)".

        Returns JSON with 'title', 'text', 'html', 'source' fields.
        Returns an error JSON if not found.
        """
        article = get_mgr().get_article(path)
        if article is None:
            return json.dumps({"error": f"Article not found: {path}"})
        return json.dumps({
            "path": article.path,
            "title": article.title,
            "text": article.content,
            "html": article.html[:4000],  # truncate for MCP
            "source": article.source,
        }, ensure_ascii=False)

    # ------------------------------------------------------------------
    # Tool: search
    # ------------------------------------------------------------------

    @mcp.tool()
    def zim_search(query: str, max_results: int = 10) -> str:
        """Search for articles by title prefix in the ZIM archive.

        Parameters
        ----------
        query       : str   Search query / title prefix.
        max_results : int   Maximum number of results (default 10).

        Returns JSON: {"results": [{"path", "title"}, ...]}
        """
        mgr = get_mgr()
        paths = mgr.search_titles(query, max_results=max_results)
        results = []
        for p in paths:
            art = mgr.get_article(p)
            if art:
                results.append({"path": p, "title": art.title})
        return json.dumps({"results": results, "count": len(results)})

    # ------------------------------------------------------------------
    # Tool: write
    # ------------------------------------------------------------------

    @mcp.tool()
    def zim_write_article(path: str, title: str, html: str) -> str:
        """Create or replace an article in the ZIM overlay.

        Parameters
        ----------
        path  : str   URL path, e.g. "A/My_Article".
        title : str   Article title.
        html  : str   HTML content of the article.

        Returns JSON: {"path", "status"}
        """
        ok = get_mgr().write_article(path, title, html)
        return json.dumps({"path": path, "status": "ok" if ok else "failed"})

    # ------------------------------------------------------------------
    # Tool: edit
    # ------------------------------------------------------------------

    @mcp.tool()
    def zim_edit_article(path: str, new_html: str, new_title: Optional[str] = None) -> str:
        """Edit an existing article's HTML content.

        Parameters
        ----------
        path      : str            Article URL path.
        new_html  : str            New HTML content.
        new_title : str, optional  New title (keeps existing if omitted).

        Returns JSON: {"path", "status"}
        """
        ok = get_mgr().edit_article(path, new_html, new_title)
        return json.dumps({
            "path": path,
            "status": "ok" if ok else "not_found",
        })

    # ------------------------------------------------------------------
    # Tool: delete
    # ------------------------------------------------------------------

    @mcp.tool()
    def zim_delete_article(path: str) -> str:
        """Soft-delete an article (tombstone in overlay).

        The article remains in the base ZIM file but is hidden.
        Use zim_restore_article to undo.

        Parameters
        ----------
        path : str   Article URL path to delete.

        Returns JSON: {"path", "deleted": bool}
        """
        ok = get_mgr().delete_article(path)
        return json.dumps({"path": path, "deleted": ok})

    # ------------------------------------------------------------------
    # Tool: restore
    # ------------------------------------------------------------------

    @mcp.tool()
    def zim_restore_article(path: str) -> str:
        """Restore a soft-deleted article.

        Parameters
        ----------
        path : str   Article URL path to restore.

        Returns JSON: {"path", "restored": bool}
        """
        ok = get_mgr().restore_article(path)
        return json.dumps({"path": path, "restored": ok})

    # ------------------------------------------------------------------
    # Tool: list modified
    # ------------------------------------------------------------------

    @mcp.tool()
    def zim_list_modified() -> str:
        """List all articles that have been created, edited, or deleted.

        Returns JSON: {"articles": [{"path", "title", "modified_at", "deleted"}, ...]}
        """
        items = get_mgr().list_modified()
        return json.dumps({"articles": items, "count": len(items)})

    # ------------------------------------------------------------------
    # Tool: list articles
    # ------------------------------------------------------------------

    @mcp.tool()
    def zim_list_articles(max_results: int = 50) -> str:
        """List overlay articles (most recently modified first).

        Parameters
        ----------
        max_results : int   Maximum entries to return (default 50).

        Returns JSON: {"articles": [...]}
        """
        items = get_mgr().list_articles(max_results=max_results)
        return json.dumps({"articles": items, "count": len(items)})

    # ------------------------------------------------------------------
    # Tool: stats
    # ------------------------------------------------------------------

    @mcp.tool()
    def zim_stats() -> str:
        """Return statistics about the ZIM archive and overlay.

        Returns JSON with zim_path, article_count, overlay_count.
        """
        mgr = get_mgr()
        stats = {
            "zim_path": mgr.zim_path,
            "overlay_path": mgr.overlay_path,
            "overlay_articles": len(mgr.list_modified()),
        }
        if mgr._archive:
            stats["article_count"] = mgr._archive.article_count
            stats["entry_count"]   = mgr._archive.entry_count
        return json.dumps(stats)

    return mcp


# ---------------------------------------------------------------------------
# CLI entry-point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse
    logging.basicConfig(level=logging.INFO)

    parser = argparse.ArgumentParser(description="ZimAgent MCP Server")
    parser.add_argument("--zim",      required=True, help="Path to .zim file")
    parser.add_argument("--overlay",  default=None,  help="Overlay DB path (optional)")
    parser.add_argument("--transport", choices=["stdio", "sse"], default="sse")
    parser.add_argument("--host",     default="127.0.0.1")
    parser.add_argument("--port",     type=int, default=8002)
    args = parser.parse_args()

    server = create_zim_mcp_server(args.zim, args.overlay)
    if args.transport == "stdio":
        server.run(transport="stdio")
    else:
        server.run(transport="sse", host=args.host, port=args.port)
