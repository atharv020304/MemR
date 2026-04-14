from __future__ import annotations
import tiktoken

_encoder: tiktoken.Encoding | None = None


def _get_encoder() -> tiktoken.Encoding:
    global _encoder
    if _encoder is None:
        _encoder = tiktoken.encoding_for_model("gpt-4")
    return _encoder


def count_tokens(text: str) -> int:
    """Count tokens using tiktoken. Falls back to ~4 chars/token estimate."""
    try:
        return len(_get_encoder().encode(text))
    except Exception:
        return len(text) // 4


def truncate(text: str, max_tokens: int) -> str:
    """Naive truncation — chops at token boundary. Use smart_truncate for snapshots."""
    enc = _get_encoder()
    tokens = enc.encode(text)
    if len(tokens) <= max_tokens:
        return text
    return enc.decode(tokens[:max_tokens])


def cleanup() -> None:
    """Free the encoder (for clean shutdown in tests)."""
    global _encoder
    _encoder = None
