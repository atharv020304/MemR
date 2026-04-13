
# ═══════════════════════════════════════════════════════════════
# FILE: memr/lens/recall.py
# ═══════════════════════════════════════════════════════════════
"""Recall lens — read-only snapshot interpretation."""

PROMPT = """\
You are reading from MemR shared memory. The content uses Decision Notation:

→  decided and shipped
↛  explored and abandoned (check reason before re-trying)
⚡ surprise / trap (always worth noting)
◌  open thread (may need resolution)
Δ  code delta with file path
⊕  external constraint (legal, client, ops)
?? question raised
>> answer found

When interpreting snapshots:
- Treat ⚡ lines as high-priority — these are traps others fell into
- Treat ↛ lines as guardrails — don't repeat abandoned approaches without new info
- Treat ◌ lines as potential action items
- Treat ⊕ lines as hard constraints that cannot be bypassed

Summarize what you learn concisely. Do not reproduce snapshot content verbatim.
"""


def get_prompt() -> str:
    return PROMPT