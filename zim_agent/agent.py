"""
ZimAgent
=========
An intelligent agent that can read, search, write, and edit ZIM archives
using TurboRag for semantic search and a local LLM for generation.

Combines:
  - ZimManager  : CRUD operations on ZIM + overlay
  - TurboRag    : semantic vector search over ZIM content
  - LangChain   : agent loop with tool calling
  - MCP server  : exposes tools to any MCP-compatible agent

Usage::

    agent = ZimAgent.create(
        zim_path="data/wikipedia_en_mini.zim",
        embed_model="models/gemma-embedding-270m-Q4_K_M.gguf",
        llm_model="models/deepseek-1.3b-Q4_K_M.gguf",
    )

    # Build semantic index
    agent.build_index(max_articles=2000)

    # Read an article
    article = agent.read("Python_(programming_language)")

    # Semantic search
    results = agent.search("programming languages history")

    # Answer a question
    answer = agent.ask("When was Python created and by whom?")

    # Write a new article
    agent.write("A/Custom_Article", "My Article", "<p>Hello world</p>")

    # Start MCP server
    agent.serve_mcp(host="127.0.0.1", port=8002)
"""

from __future__ import annotations

import logging
import os
import sys
from typing import List, Optional

logger = logging.getLogger(__name__)


class ZimAgent:
    """Intelligent ZIM archive agent with semantic search and generation.

    Parameters
    ----------
    manager : ZimManager
        ZIM CRUD manager.
    rag : TurboRag
        Semantic search + RAG engine.
    config : dict
        Runtime configuration.
    """

    SYSTEM_PROMPT = (
        "You are a knowledgeable assistant with access to a local Wikipedia archive. "
        "You can read, search, and write Wikipedia articles. "
        "Answer questions accurately based on the provided context. "
        "When writing articles, use clear, encyclopedic prose."
    )

    def __init__(self, manager, rag, config: dict) -> None:
        self.manager = manager
        self.rag = rag
        self.config = config

    # ------------------------------------------------------------------
    # Factory
    # ------------------------------------------------------------------

    @classmethod
    def create(
        cls,
        zim_path: str = "data/wikipedia_en_mini.zim",
        embed_model: str = "models/gemma-embedding-270m-Q4_K_M.gguf",
        llm_model: str = "models/deepseek-1.3b-Q4_K_M.gguf",
        index_path: str = "data/zim_index.tvim",
        overlay_path: Optional[str] = None,
        embed_dim: int = 2048,
        top_k: int = 5,
        llm_template: str = "deepseek",
    ) -> "ZimAgent":
        # Ensure turborag importable
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

        from turborag import TurboRag
        from turborag.config import (
            TurboRagConfig, EmbedderConfig, LLMConfig, IndexConfig
        )
        from turborag.llm import LLM
        from .zim_manager import ZimManager

        cfg = TurboRagConfig(
            embedder=EmbedderConfig(model_path=embed_model, dim=embed_dim),
            llm=LLMConfig(model_path=llm_model, chat_template=llm_template),
            index=IndexConfig(
                dim=embed_dim,
                bit_width=4,
                index_path=index_path,
                docstore_path=index_path.replace(".tvim", "_docs.db"),
            ),
            top_k=top_k,
        )
        llm = LLM.from_config(cfg.llm)
        rag = TurboRag(config=cfg, llm=llm)

        manager = ZimManager(zim_path, overlay_path)
        manager.open()

        config = {
            "zim_path": zim_path,
            "embed_model": embed_model,
            "llm_model": llm_model,
            "index_path": index_path,
            "top_k": top_k,
        }
        return cls(manager=manager, rag=rag, config=config)

    # ------------------------------------------------------------------
    # Index building
    # ------------------------------------------------------------------

    def build_index(
        self,
        max_articles: Optional[int] = None,
        min_words: int = 50,
        show_progress: bool = True,
    ) -> int:
        """Index the ZIM file into TurboRag for semantic search."""
        from .indexer import ZimIndexer

        indexer = ZimIndexer(
            zim_path=self.config["zim_path"],
            rag=self.rag,
        )
        return indexer.index_all(
            max_articles=max_articles,
            min_words=min_words,
            show_progress=show_progress,
        )

    # ------------------------------------------------------------------
    # Article operations
    # ------------------------------------------------------------------

    def read(self, path: str) -> Optional[str]:
        """Read an article's plain text by URL path."""
        article = self.manager.get_article(path)
        return article.content if article else None

    def read_full(self, path: str):
        """Read an article's full entry (title, text, html, source)."""
        return self.manager.get_article(path)

    def write(self, path: str, title: str, html: str) -> bool:
        """Create or replace an article in the overlay."""
        ok = self.manager.write_article(path, title, html)
        if ok:
            # Re-index the new article
            article = self.manager.get_article(path)
            if article:
                self.rag.add_document(
                    article.content,
                    {"source": "overlay", "path": path, "title": title},
                )
        return ok

    def edit(self, path: str, new_html: str, new_title: Optional[str] = None) -> bool:
        """Edit an article and update its index entry."""
        ok = self.manager.edit_article(path, new_html, new_title)
        if ok:
            article = self.manager.get_article(path)
            if article:
                self.rag.add_document(
                    article.content,
                    {"source": "overlay", "path": path, "title": article.title},
                )
        return ok

    def delete(self, path: str) -> bool:
        """Soft-delete an article."""
        return self.manager.delete_article(path)

    def restore(self, path: str) -> bool:
        """Restore a soft-deleted article."""
        return self.manager.restore_article(path)

    # ------------------------------------------------------------------
    # Search & Q&A
    # ------------------------------------------------------------------

    def search(self, query: str, k: Optional[int] = None) -> List:
        """Semantic search over indexed ZIM content."""
        return self.rag.search(query, k=k or self.config["top_k"])

    def ask(self, question: str, k: Optional[int] = None) -> str:
        """Ask a question, answered from the ZIM knowledge base."""
        answer, _ = self.rag.ask(
            question,
            k=k or self.config["top_k"],
            system=self.SYSTEM_PROMPT,
        )
        return answer

    # ------------------------------------------------------------------
    # Generation helpers
    # ------------------------------------------------------------------

    def generate_article(self, topic: str, length: str = "medium") -> str:
        """Generate a new Wikipedia-style article on a topic.

        Uses RAG context from existing articles for accuracy.
        """
        word_target = {"short": 150, "medium": 300, "long": 600}.get(length, 300)
        hits = self.rag.search(topic, k=5)
        context = "\n\n".join(h.text for h in hits)
        prompt = (
            f"Write a Wikipedia-style article about: {topic}\n\n"
            f"Use the following reference material:\n{context[:2000]}\n\n"
            f"Write approximately {word_target} words in encyclopedic style. "
            f"Start with a clear definition paragraph."
        )
        system = (
            "You are a Wikipedia article writer. Write accurate, encyclopedic articles "
            "in a neutral tone. Use facts from the provided context."
        )
        return self.rag.llm.generate(prompt, system=system, max_tokens=word_target * 2)

    def summarize_article(self, path: str) -> str:
        """Summarize an article to 2-3 sentences."""
        article = self.manager.get_article(path)
        if article is None:
            return f"Article not found: {path}"
        prompt = (
            f"Summarize this Wikipedia article in 2-3 sentences:\n\n"
            f"{article.content[:2000]}"
        )
        return self.rag.llm.generate(prompt, max_tokens=200)

    # ------------------------------------------------------------------
    # MCP server
    # ------------------------------------------------------------------

    def serve_mcp(
        self,
        host: str = "127.0.0.1",
        port: int = 8002,
        transport: str = "sse",
    ) -> None:
        """Start the MCP server (blocking)."""
        from .mcp_server import create_zim_mcp_server
        server = create_zim_mcp_server(
            self.config["zim_path"],
            self.manager.overlay_path,
        )
        server.run(transport=transport, host=host, port=port)

    # ------------------------------------------------------------------
    # Stats
    # ------------------------------------------------------------------

    def stats(self) -> dict:
        modified = self.manager.list_modified()
        return {
            **self.rag.stats(),
            "zim_path": self.config["zim_path"],
            "overlay_articles": len(modified),
            "overlay_path": self.manager.overlay_path,
        }
