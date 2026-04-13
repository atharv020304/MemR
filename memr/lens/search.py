
# ═══════════════════════════════════════════════════════════════
# FILE: memr/lens/search.py
# ═══════════════════════════════════════════════════════════════
"""Search lens — cross-vault filtered queries."""

PROMPT = """\
You are searching across MemR vault snapshots. Available filters:
- recent: N most recent snapshots
- topic: keyword match against snapshot topics
- date: YYYY-MM-DD exact date match
- surprises: snapshots containing ⚡ (traps, non-obvious bugs)
- open: snapshots containing ◌ (unresolved threads)
- abandoned: snapshots containing ↛ (dead ends)
- constraints: snapshots containing ⊕ (external constraints)

Combine filters if needed. Start broad, then narrow.
Report what you find concisely — topic, date, and the relevant signal lines.
"""


def get_prompt() -> str:
    return PROMPT
