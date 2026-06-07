# Zim-Agent-Local-(ZAL)
| ZIM CRUD agent (read/write/edit/delete) + semantic search | ZIM archives (Wikipedia)
<img width="1024" height="572" alt="image" src="https://github.com/user-attachments/assets/4396df7b-a516-451b-a1c6-ca7fd328807b" />

**Offline CRUD + semantic search agent for ZIM archives (Kiwix format). Read, write, edit, delete articles, build vector indexes, and serve via MCP – all offline, low‑resource.**
<img width="1024" height="572" alt="image" src="https://github.com/user-attachments/assets/23724676-d208-4e1f-be67-26b91d473138" />


---

## 📄 README.md for `zim-agent`

Below is a complete, ready‑to‑use `README.md` for your ZimAgent project. Place this file in the root of your GitHub repository.

```markdown
# ZimAgent

**ZimAgent** is a complete offline agent for working with **ZIM** files (the Kiwix archive format). Unlike a simple reader, it supports **CRUD** operations – you can read, write, edit, and delete articles, plus perform semantic search using **TurboRag**. It also exposes an **MCP server** so that other AI agents can manipulate ZIM archives programmatically.

---

## Features

- 📖 **Read articles** by path (e.g., `A/Python_(programming_language)`)
- ✍️ **Write new articles** (HTML content + metadata)
- ✏️ **Edit/update existing articles**
- 🗑️ **Delete articles**
- 🔍 **Semantic search** – find articles by meaning (powered by TurboRag)
- 📝 **Full‑text keyword search** (SQLite FTS5 fallback)
- 🤖 **MCP server** – expose all operations via stdio or SSE for Claude Desktop or any MCP client
- 🧠 **Offline first** – no internet required after setup

---

## Quick Start

### 1. Install dependencies

```bash
git clone https://github.com/AHX47/zim-agent.git
cd zim-agent
pip install -r requirements.txt
```

### 2. Install TurboRag (dependency)

TurboRag provides the embedding and vector search engine.

```bash
pip install turborag-ahx47   # or your published turborag package
```

### 3. Download a ZIM file (or use your own)

```bash
mkdir -p data
# Mini Wikipedia (~90 MB) for testing
wget https://download.kiwix.org/zim/wikipedia/wikipedia_en_top_mini_2024-12.zim -O data/test.zim
```

### 4. Download the embedding model

You need the Gemma 300M GGUF model (≈150 MB):

```bash
mkdir -p models
wget -O models/embeddinggemma-300m-q4_k_m.gguf \
  "https://huggingface.co/sabafallah/embeddinggemma-300m-Q4_K_M-GGUF/resolve/main/embeddinggemma-300m-q4_k_m.gguf"
```

### 5. Build the semantic index

```bash
python main.py index --zim data/test.zim --max-articles 5000
```

The index will be stored in `data/zim_index/`.

---

## Usage

### Read an article

```bash
python main.py read --path "A/Python_(programming_language)"
```

### Write a new article

```bash
python main.py write --path "A/My_New_Article" \
  --title "My New Article" \
  --html "<p>This is a brand new article.</p>"
```

### Edit an article

```bash
python main.py edit --path "A/My_New_Article" --html "<p>Updated content</p>"
```

### Delete an article

```bash
python main.py delete --path "A/My_New_Article"
```

### Ask a semantic question

```bash
python main.py ask "What is the main programming language for machine learning?"
```

### Interactive chat

```bash
python main.py chat
```

### MCP Server (for agent integration)

Start the server:

```bash
python main.py serve-mcp --port 8002 --transport sse
```

Or for stdio (Claude Desktop):

```bash
python main.py serve-mcp --transport stdio
```

#### Available MCP tools

| Tool | Description |
|------|-------------|
| `read_article(path)` | Returns HTML and plain text of an article |
| `search_articles(query, k)` | Semantic search (returns top‑k articles) |
| `write_article(path, title, html)` | Creates a new article |
| `edit_article(path, html)` | Replaces content of existing article |
| `delete_article(path)` | Removes the article |

#### Example Claude conversation

```
User: Create a new article about "Rust programming" in my ZIM.
Claude: [calls write_article with path "R/Rust_programming"]
Agent: Article created successfully.
```

---

## Architecture

```
┌─────────────────────────────────────────────────┐
│  CLI (read/write/edit/delete/ask/chat)         │
│  MCP Server (stdio/SSE)                        │
├─────────────────────────────────────────────────┤
│  ZimAgent Core                                  │
│  ┌──────────┐  ┌──────────┐  ┌──────────────┐ │
│  │ ZIM      │  │ TurboRag │  │ SQLite FTS5  │ │
│  │ Reader   │  │ Semantic │  │ Keyword      │ │
│  │ Writer   │  │ Index    │  │ Search       │ │
│  └──────────┘  └──────────┘  └──────────────┘ │
├─────────────────────────────────────────────────┤
│  Dependencies: libzim, turborag, llama-cpp     │
└─────────────────────────────────────────────────┘
```

---

## Configuration

Create a `config.yaml` (or edit the default in `main.py`):

```yaml
embed_model: "models/embeddinggemma-300m-q4_k_m.gguf"
zim_path: "data/test.zim"
index_path: "data/zim_index"
chunk_size: 512
mcp_host: "127.0.0.1"
mcp_port: 8002
```

---

## Requirements

- Python 3.10+
- Rust (only if you rebuild TurboVec – not required if using `pip install turborag-ahx47`)
- ~1 GB RAM
- ~2 GB disk space (for ZIM + index + models)
- No internet required at runtime

---

## Installation from Source

```bash
git clone https://github.com/AHX47/zim-agent.git
cd zim-agent
pip install -r requirements.txt
pip install -e .
```

---

## License

MIT

---

## Links

- **GitHub**: [AHX47/zim-agent](https://github.com/AHX47/zim-agent)
- **Related projects**: [turborag-ahx47](https://pypi.org/project/turborag-ahx47/),[turborag](https://github.com/AHX47/turborag), [turbovec](https://github.com/RyanCodrai/turbovec)
```

