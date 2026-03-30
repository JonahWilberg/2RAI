"""
Second Renaissance AI Guide — backend server.

Startup:  python server.py
Then open http://localhost:8000
"""

import json
import logging
import os
import sys
import threading
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import anthropic
import pdfplumber
import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

import config

# ── Logging ───────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

# ── Document loading ──────────────────────────────────────────────────────────

DOCUMENTS_DIR = Path(config.DOCUMENTS_FOLDER)
SUPPORTED_EXTENSIONS = {".txt", ".md", ".pdf"}

_corpus: str = ""
_corpus_lock = threading.Lock()


def _extract_pdf(path: Path) -> str | None:
    try:
        with pdfplumber.open(path) as pdf:
            pages = [page.extract_text() or "" for page in pdf.pages]
        text = "\n".join(pages).strip()
        return text if text else None
    except Exception as exc:
        log.warning("Could not parse PDF '%s': %s — skipping.", path.name, exc)
        return None


def _estimate_tokens(text: str) -> int:
    """Very rough estimate: ~4 chars per token."""
    return max(1, len(text) // 4)


def load_documents() -> None:
    global _corpus
    DOCUMENTS_DIR.mkdir(exist_ok=True)

    parts: list[str] = []
    total_chars = 0

    files = sorted(
        f for f in DOCUMENTS_DIR.iterdir()
        if f.is_file() and f.suffix.lower() in SUPPORTED_EXTENSIONS
    )

    if not files:
        log.info("No documents found in '%s'.", DOCUMENTS_DIR)
    else:
        log.info("Loading %d document(s) from '%s':", len(files), DOCUMENTS_DIR)

    for path in files:
        if path.suffix.lower() == ".pdf":
            text = _extract_pdf(path)
        else:
            try:
                text = path.read_text(encoding="utf-8").strip()
            except Exception as exc:
                log.warning("Could not read '%s': %s — skipping.", path.name, exc)
                text = None

        if not text:
            continue

        est = _estimate_tokens(text)
        log.info("  ✓ %-40s  ~%d tokens", path.name, est)
        parts.append(f"=== {path.name} ===\n{text}")
        total_chars += len(text)

    corpus = "\n\n".join(parts)
    log.info(
        "Corpus ready: %d document(s), ~%d tokens total.",
        len(parts),
        _estimate_tokens(corpus),
    )

    with _corpus_lock:
        _corpus = corpus


# ── File watcher ──────────────────────────────────────────────────────────────


class _DocumentWatcher(FileSystemEventHandler):
    """Debounces filesystem events and reloads the corpus after a short delay."""

    def __init__(self) -> None:
        self._timer: threading.Timer | None = None
        self._lock = threading.Lock()

    def _schedule(self) -> None:
        with self._lock:
            if self._timer:
                self._timer.cancel()
            self._timer = threading.Timer(1.0, self._reload)
            self._timer.start()

    def _reload(self) -> None:
        log.info("Documents folder changed — reloading corpus…")
        load_documents()

    def on_created(self, event):  # noqa: ANN001
        if not event.is_directory:
            self._schedule()

    def on_deleted(self, event):  # noqa: ANN001
        if not event.is_directory:
            self._schedule()

    def on_modified(self, event):  # noqa: ANN001
        if not event.is_directory:
            self._schedule()

    def on_moved(self, event):  # noqa: ANN001
        self._schedule()


# ── Anthropic client ──────────────────────────────────────────────────────────

load_dotenv()

_api_key = os.getenv("ANTHROPIC_API_KEY")
if not _api_key:
    log.error(
        "ANTHROPIC_API_KEY environment variable is not set.\n"
        "Copy .env.example to .env and add your key, then restart."
    )
    sys.exit(1)

_client = anthropic.Anthropic(api_key=_api_key)

# ── FastAPI app ───────────────────────────────────────────────────────────────


@asynccontextmanager
async def _lifespan(app: FastAPI):  # noqa: ANN001
    # Startup
    log.info("=" * 60)
    log.info("Second Renaissance AI Guide")
    log.info("=" * 60)
    load_documents()

    observer = Observer()
    watcher = _DocumentWatcher()
    observer.schedule(watcher, str(DOCUMENTS_DIR), recursive=False)
    observer.start()
    log.info("Watching '%s' for changes.", DOCUMENTS_DIR)
    log.info("Server ready → http://localhost:8000")
    log.info("=" * 60)

    yield

    # Shutdown
    observer.stop()
    observer.join()


app = FastAPI(lifespan=_lifespan)

# Serve static files (the frontend)
app.mount("/static", StaticFiles(directory="static"), name="static")


@app.get("/")
async def index() -> FileResponse:
    return FileResponse("static/index.html")


# ── Chat endpoint ─────────────────────────────────────────────────────────────


class _Message(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    message: str
    history: list[_Message] = []


def _build_system(corpus: str) -> list[dict[str, Any]]:
    """Build the system prompt blocks with prompt caching on the corpus."""
    blocks: list[dict[str, Any]] = [
        {"type": "text", "text": config.SYSTEM_PROMPT_PREAMBLE},
    ]
    if corpus:
        blocks.append(
            {
                "type": "text",
                "text": (
                    "\n\n"
                    "--- DOCUMENT CORPUS (use this as your primary reference) ---\n\n"
                    f"{corpus}\n\n"
                    "--- END OF DOCUMENT CORPUS ---"
                ),
                # Enable prompt caching so the large corpus isn't re-processed
                # on every turn — saves cost and latency.
                "cache_control": {"type": "ephemeral"},
            }
        )
    return blocks


@app.post("/chat")
async def chat(req: ChatRequest) -> StreamingResponse:
    with _corpus_lock:
        corpus = _corpus

    system = _build_system(corpus)

    messages: list[dict[str, Any]] = [
        {"role": m.role, "content": m.content} for m in req.history
    ]
    messages.append({"role": "user", "content": req.message})

    def _generate():
        try:
            with _client.messages.stream(
                model=config.MODEL,
                max_tokens=config.MAX_TOKENS,
                system=system,  # type: ignore[arg-type]
                messages=messages,
            ) as stream:
                for text in stream.text_stream:
                    yield f"data: {json.dumps({'type': 'text', 'text': text})}\n\n"
            yield f"data: {json.dumps({'type': 'done'})}\n\n"

        except anthropic.AuthenticationError:
            msg = "Authentication failed — check your ANTHROPIC_API_KEY."
            log.error(msg)
            yield f"data: {json.dumps({'type': 'error', 'message': msg})}\n\n"

        except anthropic.RateLimitError:
            msg = "Rate limit reached. Please wait a moment and try again."
            log.warning(msg)
            yield f"data: {json.dumps({'type': 'error', 'message': msg})}\n\n"

        except anthropic.APIError as exc:
            msg = f"API error: {exc}"
            log.error(msg)
            yield f"data: {json.dumps({'type': 'error', 'message': msg})}\n\n"

        except Exception as exc:
            msg = f"Unexpected error: {exc}"
            log.exception(msg)
            yield f"data: {json.dumps({'type': 'error', 'message': msg})}\n\n"

    return StreamingResponse(
        _generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",  # Disable Nginx buffering if behind a proxy
        },
    )


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    uvicorn.run("server:app", host="0.0.0.0", port=8000, reload=False)
