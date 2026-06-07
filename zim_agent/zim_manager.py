"""
ZimManager
==========
Read, write, edit, and create articles in ZIM archives.

ZIM files are read-only by design — modifications are stored in a
local SQLite "overlay" database.  The overlay is transparent: when
you request an article, the manager merges the overlay on top of
the base ZIM content.

Overlay operations:
  - write_article(path, title, html)  — create or replace an article
  - edit_article(path, new_text)      — update the text of an article
  - delete_article(path)              — tombstone an article
  - list_modified()                   — list overlay entries

The merged content can be exported back to a new ZIM file using
python-libzim's writer API (requires libzim >= 9.x).
"""

from __future__ import annotations

import logging
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

logger = logging.getLogger(__name__)


@dataclass
class ArticleEntry:
    """An article record — from ZIM or overlay."""
    path: str
    title: str
    content: str            # plain text
    html: str               # HTML source
    source: str             # "zim" | "overlay"
    modified_at: Optional[float] = None


class ZimManager:
    """ZIM file manager with an editable overlay.

    Parameters
    ----------
    zim_path : str
        Path to the base .zim archive (read-only).
    overlay_path : str, optional
        Path to the SQLite overlay DB.  Defaults to ``<zim_path>.overlay.db``.
    """

    def __init__(
        self,
        zim_path: str,
        overlay_path: Optional[str] = None,
    ) -> None:
        self.zim_path = zim_path
        self.overlay_path = overlay_path or (zim_path + ".overlay.db")
        self._archive = None  # lazy libzim Archive
        self._db = self._open_overlay(self.overlay_path)

    # ------------------------------------------------------------------
    # Open / close ZIM
    # ------------------------------------------------------------------

    def open(self) -> "ZimManager":
        try:
            from libzim.reader import Archive
            self._archive = Archive(self.zim_path)
            logger.info("Opened ZIM: %s  (%d articles)", self.zim_path, self._archive.article_count)
        except ImportError:
            logger.warning("python-libzim not installed — base ZIM access disabled.")
        return self

    def __enter__(self) -> "ZimManager":
        return self.open()

    def __exit__(self, *_) -> None:
        self._archive = None

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    def get_article(self, path: str) -> Optional[ArticleEntry]:
        """Get an article — overlay takes precedence over ZIM."""
        # 1. Check overlay first
        overlay = self._overlay_get(path)
        if overlay:
            return overlay

        # 2. Fall back to ZIM
        return self._zim_get(path)

    def search_titles(self, prefix: str, max_results: int = 20) -> List[str]:
        """Title prefix search (overlay + ZIM)."""
        results = []
        # Overlay titles
        cur = self._db.execute(
            "SELECT path FROM articles WHERE title LIKE ? AND deleted=0 LIMIT ?",
            (f"{prefix}%", max_results),
        )
        results.extend(row[0] for row in cur.fetchall())

        # ZIM title search
        if self._archive:
            try:
                lp = prefix.lower()
                for i in range(min(self._archive.entry_count, 50_000)):
                    entry = self._archive.get_entry_by_id(i)
                    if str(entry.title).lower().startswith(lp):
                        results.append(str(entry.path))
                        if len(results) >= max_results:
                            break
            except Exception:
                pass
        return list(dict.fromkeys(results))[:max_results]

    def list_articles(self, max_results: int = 100) -> List[dict]:
        """List articles — overlay entries + first N from ZIM."""
        rows = []
        cur = self._db.execute(
            "SELECT path, title, modified_at, deleted FROM articles ORDER BY modified_at DESC LIMIT ?",
            (max_results,),
        )
        for path, title, ts, deleted in cur.fetchall():
            rows.append({
                "path": path,
                "title": title,
                "modified_at": ts,
                "deleted": bool(deleted),
                "source": "overlay",
            })
        return rows

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------

    def write_article(self, path: str, title: str, html: str) -> bool:
        """Create or replace an article in the overlay."""
        from .zim_reader import Article as _Art
        text = _Art._strip_html(html)
        self._db.execute(
            "INSERT OR REPLACE INTO articles "
            "(path, title, html, text, modified_at, deleted) VALUES (?,?,?,?,?,0)",
            (path, title, html, text, time.time()),
        )
        self._db.commit()
        logger.info("Wrote article: %s (%s)", path, title)
        return True

    def edit_article(self, path: str, new_html: str, new_title: Optional[str] = None) -> bool:
        """Edit the HTML of an existing article."""
        existing = self.get_article(path)
        if existing is None:
            logger.warning("edit_article: path not found: %s", path)
            return False
        title = new_title or existing.title
        return self.write_article(path, title, new_html)

    def delete_article(self, path: str) -> bool:
        """Soft-delete an article (tombstone in overlay)."""
        # Check it exists
        existing = self.get_article(path)
        if existing is None:
            return False
        # If it's in overlay, mark deleted
        cur = self._db.execute("SELECT 1 FROM articles WHERE path=?", (path,))
        if cur.fetchone():
            self._db.execute(
                "UPDATE articles SET deleted=1, modified_at=? WHERE path=?",
                (time.time(), path),
            )
        else:
            # Create a tombstone row
            self._db.execute(
                "INSERT INTO articles (path, title, html, text, modified_at, deleted) "
                "VALUES (?,?,?,?,?,1)",
                (path, existing.title, "", "", time.time()),
            )
        self._db.commit()
        logger.info("Deleted (tombstoned): %s", path)
        return True

    def restore_article(self, path: str) -> bool:
        """Un-delete a tombstoned article."""
        cur = self._db.execute(
            "UPDATE articles SET deleted=0 WHERE path=? AND deleted=1", (path,)
        )
        self._db.commit()
        return cur.rowcount > 0

    def list_modified(self) -> List[dict]:
        """Return all overlay records (created, edited, deleted)."""
        cur = self._db.execute(
            "SELECT path, title, modified_at, deleted FROM articles ORDER BY modified_at DESC"
        )
        return [
            {"path": p, "title": t, "modified_at": ts, "deleted": bool(d)}
            for p, t, ts, d in cur.fetchall()
        ]

    # ------------------------------------------------------------------
    # Export
    # ------------------------------------------------------------------

    def export_overlay_to_zim(self, output_path: str) -> int:
        """Write all overlay articles (non-deleted) to a new ZIM file.

        Requires libzim >= 9.x with writer support.
        Returns number of articles written.
        """
        try:
            from libzim.writer import Creator, Article as WArticle, Blob
        except ImportError:
            raise ImportError(
                "libzim writer support requires libzim >= 9.x: pip install libzim"
            )

        cur = self._db.execute(
            "SELECT path, title, html FROM articles WHERE deleted=0"
        )
        rows = cur.fetchall()
        if not rows:
            logger.warning("No overlay articles to export.")
            return 0

        class _Article(WArticle):
            def __init__(self, path, title, html):
                super().__init__()
                self._path = path
                self._title = title
                self._html = html.encode("utf-8")

            def get_url(self):      return self._path
            def get_title(self):    return self._title
            def get_mime_type(self): return "text/html"
            def is_redirect(self):  return False
            def get_data(self):     return Blob(self._html)

        with Creator(output_path) as creator:
            for path, title, html in rows:
                creator.add_article(_Article(path, title, html))

        logger.info("Exported %d articles to %s", len(rows), output_path)
        return len(rows)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _open_overlay(self, path: str) -> sqlite3.Connection:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        con = sqlite3.connect(path, check_same_thread=False)
        con.execute(
            "CREATE TABLE IF NOT EXISTS articles "
            "(path TEXT PRIMARY KEY, title TEXT, html TEXT, text TEXT, "
            "modified_at REAL, deleted INTEGER DEFAULT 0)"
        )
        con.execute("CREATE INDEX IF NOT EXISTS idx_title ON articles(title)")
        con.commit()
        return con

    def _overlay_get(self, path: str) -> Optional[ArticleEntry]:
        cur = self._db.execute(
            "SELECT title, html, text, modified_at, deleted FROM articles WHERE path=?",
            (path,),
        )
        row = cur.fetchone()
        if row is None:
            return None
        title, html, text, ts, deleted = row
        if deleted:
            return None  # Treat tombstone as not found
        return ArticleEntry(
            path=path,
            title=title,
            content=text,
            html=html,
            source="overlay",
            modified_at=ts,
        )

    def _zim_get(self, path: str) -> Optional[ArticleEntry]:
        if self._archive is None:
            return None
        try:
            entry = self._archive.get_entry_by_path(path)
            item = entry.get_item()
            html = bytes(item.content).decode("utf-8", errors="replace")
            from .zim_reader import Article as _Art
            text = _Art._strip_html(html)
            return ArticleEntry(
                path=path,
                title=str(entry.title),
                content=text,
                html=html,
                source="zim",
            )
        except KeyError:
            return None
