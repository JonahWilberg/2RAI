# ── Configuration ─────────────────────────────────────────────────────────────

MODEL = "claude-sonnet-4-6"
MAX_TOKENS = 1024
DOCUMENTS_FOLDER = "documents"

# Load character & style protocol from protocol.md at the project root.
# Edit that file to change the bot's tone, persona, and behaviour —
# no code changes needed.
def _load_protocol() -> str:
    import os
    protocol_path = os.path.join(os.path.dirname(__file__), "protocol.md")
    try:
        with open(protocol_path, "r", encoding="utf-8") as f:
            return f.read().strip()
    except FileNotFoundError:
        return (
            "You are a helpful guide to the Second Renaissance movement. "
            "You explain its ideas clearly and thoughtfully, drawing on the "
            "provided documents where relevant."
        )

SYSTEM_PROMPT_PREAMBLE = _load_protocol()
