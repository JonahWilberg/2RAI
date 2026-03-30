# Second Renaissance — AI Guide

A web-based chatbot that explains the ideas of the Second Renaissance movement,
powered by Claude (`claude-sonnet-4-6`). Drop documents into a folder and the
bot uses them as its knowledge base — no code changes required.

---

## Quick start

### 1. Install dependencies

```bash
pip install -r requirements.txt
```

Requires Python 3.10+.

### 2. Set your API key

```bash
cp .env.example .env
# Open .env and replace the placeholder with your real key:
#   ANTHROPIC_API_KEY=sk-ant-...
```

### 3. Add documents

Place `.txt`, `.md`, or `.pdf` files in the `documents/` folder.
See `documents/placeholder.txt` for full guidance.

### 4. Run the server

```bash
python server.py
```

Open **http://localhost:8000** in your browser.

---

## Project structure

```
2RAI/
├── server.py          # FastAPI backend — document loading, chat endpoint
├── config.py          # Model, max_tokens, system prompt preamble
├── requirements.txt
├── .env.example       # Copy to .env and add your API key
├── documents/         # ← Drop your content here
│   └── placeholder.txt
├── static/
│   └── index.html     # Single-page chat UI
└── README.md
```

---

## Configuration

Edit `config.py` to change any of these settings without touching the server code:

| Setting                | Default              | Description                            |
|------------------------|----------------------|----------------------------------------|
| `MODEL`                | `claude-sonnet-4-6`  | Anthropic model to use                 |
| `MAX_TOKENS`           | `1024`               | Maximum tokens in each response        |
| `DOCUMENTS_FOLDER`     | `documents`          | Path to the documents folder           |
| `SYSTEM_PROMPT_PREAMBLE` | *(see file)*       | Bot persona and instructions           |

---

## Document management

The `documents/` folder is the only place you need to touch to manage content:

- **Add** a file → corpus reloads automatically within ~1 second
- **Remove** a file → corpus reloads automatically
- **Edit** a file → corpus reloads automatically

Supported formats: `.txt`, `.md`, `.pdf`

If a PDF cannot be parsed (scanned images, corrupted files), a warning is logged
and the file is skipped — the server keeps running with the remaining documents.

### Prompt caching

The full document corpus is sent as a cached system-prompt block. The first
request after a corpus change pays full input-token cost; subsequent requests
within 5 minutes reuse the Anthropic prompt cache (~90 % cheaper for the
document portion). Cache usage is visible in the Anthropic console.

---

## How it works

1. **Startup** — `server.py` reads every supported file in `documents/`, extracts
   text (using `pdfplumber` for PDFs), and assembles a single corpus string.
2. **File watching** — `watchdog` monitors the folder; any change triggers a
   debounced reload (1 s delay to avoid partial-write races).
3. **Chat endpoint** — `POST /chat` accepts `{ message, history }` and calls the
   Claude API with streaming enabled. The corpus is injected into the system
   prompt with `cache_control: ephemeral`.
4. **Frontend** — A plain HTML/JS page reads the SSE stream token-by-token and
   renders a live, markdown-aware response.

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---------|-------------|-----|
| `ANTHROPIC_API_KEY … not set` on startup | Missing env var | Add key to `.env` |
| PDF skipped with warning | Scanned/image-only PDF | Use a text-based PDF or convert to `.txt` |
| Responses cut off | `MAX_TOKENS` too low | Increase in `config.py` |
| Old content still appearing | Cache TTL (5 min) | Wait or send a new message after the TTL expires |
