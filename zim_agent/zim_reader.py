"""
ZIM Reader
==========
Read articles from offline .zim archives (Kiwix / Wikipedia).

Requires: python-libzim
  pip install libzim

ZIM files can be downloaded from:
  https://wiki.kiwix.org/wiki/Content_in_all_languages
  https://download.kiwix.org/zim/wikipedia/

Example::

    reader = ZimReader("wikipedia_en_mini.zim")
    article = reader.get_article("Python_(programming_language)")
    print(article.title)
    print(article.text[:500])

    # Stream all articles for indexing
    for article in reader.iter_articles(max_articles=1000):
        print(article.title)
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Iterator, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class Article:
    """A single article extracted from a ZIM file."""
    title: str
    path: str
    text: str          # Plain text (HTML stripped)
    html: str          # Raw HTML
    namespace: str     # "A" for articles, "I" for images, etc.
    word_count: int = 0

    @classmethod
    def from_entry(cls, entry, namespace: str = "A") -> Optional["Article"]:
        """Build an Article from a libzim entry."""
        try:
            item = entry.get_item()
            raw = bytes(item.content).decode("utf-8", errors="replace")
            text = cls._strip_html(raw)
            return cls(
                title=str(entry.title),
                path=str(entry.path),
                text=text,
                html=raw,
                namespace=namespace,
                word_count=len(text.split()),
            )
        except Exception as exc:
            logger.debug("Skipping entry %s: %s", getattr(entry, "path", "?"), exc)
            return None

    @staticmethod
    def _strip_html(html: str) -> str:
        """Very fast HTML → plain text (no external dep)."""
        # Remove scripts and styles
        html = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", html, flags=re.DOTALL | re.IGNORECASE)
        # Remove HTML tags
        html = re.sub(r"<[^>]+>", " ", html)
        # Decode common entities
        html = (
            html.replace("&amp;", "&")
            .replace("&lt;", "<")
            .replace("&gt;", ">")
            .replace("&nbsp;", " ")
            .replace("&#39;", "'")
            .replace("&quot;", '"')
        )
        # Collapse whitespace
        html = re.sub(r"\s+", " ", html).strip()
        return html


class ZimReader:
    """Read-only interface to a .zim archive.

    Parameters
    ----------
    path : str
        Path to the .zim file.
    """

    def __init__(self, path: str) -> None:
        self.path = path
        self._archive = None

    # ------------------------------------------------------------------
    # Open / close
    # ------------------------------------------------------------------

    def open(self) -> "ZimReader":
        try:
            from libzim.reader import Archive
        except ImportError:
            raise ImportError(
                "python-libzim is required: pip install libzim\n"
                "ZIM files: https://download.kiwix.org/zim/wikipedia/"
            )
        self._archive = Archive(self.path)
        logger.info(
            "Opened ZIM: %s  (articles=%d)",
            self.path,
            self._archive.article_count,
        )
        return self

    def close(self) -> None:
        self._archive = None

    def __enter__(self) -> "ZimReader":
        return self.open()

    def __exit__(self, *_) -> None:
        self.close()

    # ------------------------------------------------------------------
    # Article access
    # ------------------------------------------------------------------

    @property
    def article_count(self) -> int:
        return self._archive.article_count if self._archive else 0

    def get_article(self, path_or_title: str) -> Optional[Article]:
        """Retrieve a specific article by URL path or title."""
        arch = self._require_open()
        try:
            entry = arch.get_entry_by_path(path_or_title)
            return Article.from_entry(entry)
        except KeyError:
            pass
        # Try by title (slower)
        try:
            entry = arch.get_entry_by_title(path_or_title)
            return Article.from_entry(entry)
        except KeyError:
            return None

    def iter_articles(
        self,
        max_articles: Optional[int] = None,
        min_words: int = 50,
        namespace: str = "A",
    ) -> Iterator[Article]:
        """Iterate over all articles in the ZIM file.

        Parameters
        ----------
        max_articles : int, optional
            Stop after this many articles (default: no limit).
        min_words : int
            Skip articles with fewer words (filters stubs).
        namespace : str
            ZIM namespace to iterate; "A" = articles.
        """
        arch = self._require_open()
        count = 0
        for i in range(arch.entry_count):
            entry = arch.get_entry_by_id(i)
            if str(getattr(entry, "namespace", "?")) != namespace:
                continue
            article = Article.from_entry(entry, namespace)
            if article is None:
                continue
            if article.word_count < min_words:
                continue
            yield article
            count += 1
            if max_articles and count >= max_articles:
                break

    def search(self, query: str, max_results: int = 10) -> List[Article]:
        """Use the ZIM file's built-in full-text search (if available).

        Falls back to title prefix search if FTS is not indexed.
        """
        arch = self._require_open()
        results: List[Article] = []
        try:
            from libzim.search import Query, Searcher
            searcher = Searcher(arch)
            q = Query().set_query(query)
            search = searcher.search(q)
            hits = search.getResults(0, max_results)
            for entry in hits:
                article = Article.from_entry(entry)
                if article:
                    results.append(article)
        except Exception:
            # Fallback: linear title scan
            query_lower = query.lower()
            for i in range(min(arch.entry_count, 50_000)):
                try:
                    entry = arch.get_entry_by_id(i)
                    if query_lower in str(entry.title).lower():
                        article = Article.from_entry(entry)
                        if article:
                            results.append(article)
                            if len(results) >= max_results:
                                break
                except Exception:
                    continue
        return results

    def _require_open(self):
        if self._archive is None:
            self.open()
        return self._archive
