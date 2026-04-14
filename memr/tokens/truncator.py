"""
Priority order (highest to lowest):
  1. ⚡ surprises   — traps others must avoid
  2. ⊕  constraints — hard rules that can't be broken  
  3. →  decisions   — what was shipped and why
  4. ↛  abandoned   — what was rejected and why
  5. ◌  open        — unresolved threads
  6. Δ  deltas      — file changes
  7. ?? / >>        — Q&A pairs
  8. Plain lines    — everything else
"""

from __future__ import annotations
from memr.types import Signal
from memr.snapshot.parser import SignalParser, ParsedLine
from memr.tokens.counter import count_tokens


# Signal priority — lower number = higher priority (kept first)
SIGNAL_PRIORITY: dict[Signal | None, int] = {
    Signal.SURPRISE:  0,
    Signal.CONTEXT:   1,
    Signal.DECIDED:   2,
    Signal.ABANDONED: 3,
    Signal.OPEN:      4,
    Signal.DELTA:     5,
    Signal.QUESTION:  6,
    Signal.ANSWER:    6,
    None:             7,
}


def smart_truncate(content: str, max_tokens: int) -> str:
    """
    Truncate snapshot content to fit within a token budget,
    keeping the most important signal lines.

    If the content already fits, returns it unchanged.
    Otherwise, sorts lines by signal priority and takes
    as many as will fit.
    """
    current = count_tokens(content)
    if current <= max_tokens:
        return content

    parser = SignalParser()
    lines = parser.parse(content)

    if not lines:
        from memr.tokens.counter import truncate
        return truncate(content, max_tokens)

    # Sort by priority (keep highest-priority lines first)
    sorted_lines = sorted(
        lines,
        key=lambda l: SIGNAL_PRIORITY.get(l.signal, 7),
    )

    # Greedily take lines until budget is exhausted
    kept: list[ParsedLine] = []
    tokens_used = 0

    for line in sorted_lines:
        line_tokens = count_tokens(line.raw)
        if tokens_used + line_tokens > max_tokens:
            continue  # skip this line, try smaller ones
        kept.append(line)
        tokens_used += line_tokens

    # Re-sort kept lines by their original order for readability
    original_order = {id(l): i for i, l in enumerate(lines)}
    kept.sort(key=lambda l: original_order.get(id(l), 999))

    result = "\n".join(l.raw for l in kept)

    # Add truncation notice if we dropped lines
    if len(kept) < len(lines):
        dropped = len(lines) - len(kept)
        result += f"\n[... {dropped} lower-priority lines truncated to fit budget]"

    return result
