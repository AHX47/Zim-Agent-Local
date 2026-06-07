"""
ZIM Indexer
===========
Reads a .zim archive and indexes all articles into TurboRag.

Usage::

    indexer = ZimIndexer(
        zim_path="wikipedia_en_mini.zim",
        rag=my_turborag,
    )
    indexer.index_all(max_articles=5000, show_progress=True)
    indexer.save()

The indexer stores the progress in a SQLite checkpoint so it can resume
after an interruption without re-embedding already-indexed articles.
"""

from __future__ import annotations

import logging
import os
import sqlite3
import time
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


class ZimIndexer:
    """Index a ZIM archive into TurboRag.

    Parameters
    ----------
    zim_path : str
        Path to the .zim file.
    rag : TurboRag
        The TurboRag instance to write into.
    checkpoint_path : str, optional
        SQLite DB for progress checkpointing.  Defaults to
        ``<zim_path>.checkpoint.db``.
    chunk_size : int
        Max words per chunk (articles are split into chunks).
    chunk_overlap : int
        Overlap words between adjacent chunks.
    """

    def __init__(
        self,
        zim_path: str,
        rag,
        checkpoint_path: Optional[str] = None,
        chunk_size: int = 400,
        chunk_overlap: int = 80,
    ) -> None:
        self.zim_path = zim_path
        self.rag = rag
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap

        cp = checkpoint_path or (zim_path + ".checkpoint.db")
        self._ckpt = self._open_checkpoint(cp)

    # ------------------------------------------------------------------
    # Indexing
    # ------------------------------------------------------------------

    def index_all(
        self,
        max_articles: Optional[int] = None,
        min_words: int = 50,
        show_progress: bool = True,
        save_every: int = 500,
    ) -> int:
        """Index the entire ZIM file.  Returns the number of chunks indexed."""
        from .zim_reader import ZimReader

        reader = ZimReader(self.zim_path)
        reader.open()

        total_chunks = 0
        article_count = 0
        start = time.time()

        try:
            for article in reader.iter_articles(
                max_articles=max_articles, min_words=min_words
            ):
                # Skip already-indexed articles (resumable)
                if self._is_indexed(article.path):
                    continue

                chunks = self.rag._chunk_text(
                    article.text, self.chunk_size, self.chunk_overlap
                )
                if not chunks:
                    continue

                metadatas = [
                    {
                        "source": "wikipedia",
                        "zim_file": os.path.basename(self.zim_path),
                        "title": article.title,
                        "path": article.path,
                        "chunk_index": i,
                        "total_chunks": len(chunks),
                    }
                    for i in range(len(chunks))
                ]

                self.rag.add_documents(chunks, metadatas)
                self._mark_indexed(article.path)

                total_chunks += len(chunks)
                article_count += 1

                if show_progress and article_count % 100 == 0:
                    elapsed = time.time() - start
                    rate = article_count / max(elapsed, 0.1)
                    logger.info(
                        "[ZimIndexer] %d articles / %d chunks  (%.1f art/s)",
                        article_count,
                        total_chunks,
                        rate,
                    )

                if article_count % save_every == 0:
                    self.rag.save()

        finally:
            reader.close()

        self.rag.save()
        elapsed = time.time() - start
        logger.info(
            "[ZimIndexer] Done: %d articles, %d chunks in %.1fs",
            article_count, total_chunks, elapsed,
        )
        return total_chunks

    def index_article(self, title: str) -> int:
        """Index a single article by title.  Returns number of chunks added."""
        from .zim_reader import ZimReader

        reader = ZimReader(self.zim_path)
        reader.open()
        article = reader.get_article(title)
        reader.close()

        if article is None:
            logger.warning("Article not found: %s", title)
            return 0

        chunks = self.rag._chunk_text(article.text, self.chunk_size, self.chunk_overlap)
        metadatas = [
            {
                "source": "wikipedia",
                "title": article.title,
                "path": article.path,
                "chunk_index": i,
                "total_chunks": len(chunks),
            }
            for i in range(len(chunks))
        ]
        self.rag.add_documents(chunks, metadatas)
        self._mark_indexed(article.path)
        return len(chunks)

    def save(self) -> None:
        self.rag.save()

    # ------------------------------------------------------------------
    # Checkpoint helpers
    # ------------------------------------------------------------------

    def _open_checkpoint(self, path: str) -> sqlite3.Connection:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        con = sqlite3.connect(path, check_same_thread=False)
        con.execute(
            "CREATE TABLE IF NOT EXISTS indexed (path TEXT PRIMARY KEY, ts REAL)"
        )
        con.commit()
        return con

    def _is_indexed(self, path: str) -> bool:
        cur = self._ckpt.execute("SELECT 1 FROM indexed WHERE path=?", (path,))
        return cur.fetchone() is not None

    def _mark_indexed(self, path: str) -> None:
        self._ckpt.execute(
            "INSERT OR IGNORE INTO indexed (path, ts) VALUES (?,?)",
            (path, time.time()),
        )
        self._ckpt.commit()

    @property
    def indexed_count(self) -> int:
        cur = self._ckpt.execute("SELECT COUNT(*) FROM indexed")
        return cur.fetchone()[0]
