#!/usr/bin/env python3
"""
ZimAgent — main entry point
============================
Usage:

  python main.py index --zim data/wiki.zim --max-articles 3000
  python main.py read --path "A/Python_(programming_language)"
  python main.py search "machine learning algorithms"
  python main.py ask "What is the Turing test?"
  python main.py write --path "A/My_Topic" --title "My Topic" --file article.html
  python main.py edit  --path "A/My_Topic" --file updated.html
  python main.py delete --path "A/Old_Article"
  python main.py generate "Quantum computing" --save
  python main.py serve-mcp --port 8002
  python main.py stats
"""

import argparse
import logging
import os
import sys

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)

DEFAULT_ZIM         = os.getenv("ZIM_PATH",         "data/wikipedia_en_mini.zim")
DEFAULT_EMBED_MODEL = os.getenv("ZIM_EMBED_MODEL",  "models/gemma-embedding-270m-Q4_K_M.gguf")
DEFAULT_LLM_MODEL   = os.getenv("ZIM_LLM_MODEL",   "models/deepseek-1.3b-Q4_K_M.gguf")
DEFAULT_INDEX_PATH  = os.getenv("ZIM_INDEX_PATH",  "data/zim_index.tvim")
DEFAULT_TOP_K       = int(os.getenv("ZIM_TOP_K",   "5"))


def _build_agent(args):
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
    from zim_agent import ZimAgent
    return ZimAgent.create(
        zim_path=args.zim,
        embed_model=args.embed_model,
        llm_model=args.llm_model,
        index_path=args.index_path,
        top_k=args.top_k,
        llm_template=args.llm_template,
    )


def cmd_index(args):
    agent = _build_agent(args)
    n = agent.build_index(max_articles=args.max_articles, show_progress=True)
    print(f"\n✓ Indexed {n} chunks")


def cmd_read(args):
    agent = _build_agent(args)
    text = agent.read(args.path)
    if text is None:
        print(f"Article not found: {args.path}")
    else:
        print(text[:3000])


def cmd_search(args):
    agent = _build_agent(args)
    query = " ".join(args.query)
    hits = agent.search(query, k=args.top_k)
    for i, h in enumerate(hits, 1):
        title = h.metadata.get("title", "?")
        print(f"\n[{i}] {title}  (score={h.score:.3f})")
        print(f"    {h.text[:300]}")


def cmd_ask(args):
    agent = _build_agent(args)
    question = " ".join(args.question)
    print(f"\nQ: {question}\n")
    answer = agent.ask(question)
    print(f"A: {answer}\n")


def cmd_write(args):
    agent = _build_agent(args)
    html = open(args.file).read() if args.file else args.html or "<p>Empty article</p>"
    ok = agent.write(args.path, args.title, html)
    print("✓ Written" if ok else "✗ Failed")


def cmd_edit(args):
    agent = _build_agent(args)
    html = open(args.file).read() if args.file else args.html
    ok = agent.edit(args.path, html, getattr(args, "title", None))
    print("✓ Edited" if ok else "✗ Failed (not found?)")


def cmd_delete(args):
    agent = _build_agent(args)
    ok = agent.delete(args.path)
    print("✓ Deleted" if ok else "✗ Not found")


def cmd_generate(args):
    agent = _build_agent(args)
    topic = " ".join(args.topic)
    print(f"Generating article: {topic} …\n")
    content = agent.generate_article(topic, length=args.length)
    print(content)
    if args.save:
        path = f"A/{topic.replace(' ', '_')}"
        agent.write(path, topic, f"<p>{content}</p>")
        print(f"\n✓ Saved as {path}")


def cmd_serve_mcp(args):
    agent = _build_agent(args)
    print(f"Starting ZimAgent MCP server on {args.host}:{args.port} …")
    agent.serve_mcp(host=args.host, port=args.port, transport=args.transport)


def cmd_stats(args):
    import json
    agent = _build_agent(args)
    print(json.dumps(agent.stats(), indent=2))


def main():
    parser = argparse.ArgumentParser(
        prog="zim_agent",
        description="ZimAgent — ZIM archive CRUD + semantic search + LLM generation",
    )
    parser.add_argument("--zim",          default=DEFAULT_ZIM)
    parser.add_argument("--embed-model",  default=DEFAULT_EMBED_MODEL)
    parser.add_argument("--llm-model",    default=DEFAULT_LLM_MODEL)
    parser.add_argument("--index-path",   default=DEFAULT_INDEX_PATH)
    parser.add_argument("--top-k",        default=DEFAULT_TOP_K, type=int)
    parser.add_argument("--llm-template", default="deepseek",
                        help="chatml | deepseek | llama")

    sub = parser.add_subparsers(dest="command", required=True)

    # index
    p = sub.add_parser("index")
    p.add_argument("--max-articles", type=int, default=None)
    p.set_defaults(func=cmd_index)

    # read
    p = sub.add_parser("read")
    p.add_argument("--path", required=True)
    p.set_defaults(func=cmd_read)

    # search
    p = sub.add_parser("search")
    p.add_argument("query", nargs="+")
    p.set_defaults(func=cmd_search)

    # ask
    p = sub.add_parser("ask")
    p.add_argument("question", nargs="+")
    p.set_defaults(func=cmd_ask)

    # write
    p = sub.add_parser("write")
    p.add_argument("--path",  required=True)
    p.add_argument("--title", required=True)
    p.add_argument("--file",  default=None, help="HTML file path")
    p.add_argument("--html",  default=None, help="HTML string (if no --file)")
    p.set_defaults(func=cmd_write)

    # edit
    p = sub.add_parser("edit")
    p.add_argument("--path",  required=True)
    p.add_argument("--title", default=None)
    p.add_argument("--file",  default=None)
    p.add_argument("--html",  default=None)
    p.set_defaults(func=cmd_edit)

    # delete
    p = sub.add_parser("delete")
    p.add_argument("--path", required=True)
    p.set_defaults(func=cmd_delete)

    # generate
    p = sub.add_parser("generate")
    p.add_argument("topic", nargs="+")
    p.add_argument("--length", choices=["short", "medium", "long"], default="medium")
    p.add_argument("--save", action="store_true")
    p.set_defaults(func=cmd_generate)

    # serve-mcp
    p = sub.add_parser("serve-mcp")
    p.add_argument("--host",      default="127.0.0.1")
    p.add_argument("--port",      type=int, default=8002)
    p.add_argument("--transport", choices=["sse", "stdio"], default="sse")
    p.set_defaults(func=cmd_serve_mcp)

    # stats
    p = sub.add_parser("stats")
    p.set_defaults(func=cmd_stats)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
