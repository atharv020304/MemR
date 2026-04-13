
# ═══════════════════════════════════════════════════════════════
# FILE: memr/lens/compact.py
# ═══════════════════════════════════════════════════════════════
"""Compact lens — merge and prune instructions."""

PROMPT = """\
You are compacting MemR vault snapshots. Two strategies:

merge_recent: Combine N recent snapshots into one.
  - Deduplicate → lines (keep the latest version of each decision)
  - Resolve ?? / >> pairs (question + answer become a single → line)
  - ALWAYS keep all ⚡ lines (surprises are never stale)
  - ALWAYS keep all ⊕ lines (constraints remain unless explicitly lifted)
  - Remove ↛ lines whose replacement → is already captured
  - Keep ◌ lines unless a >> resolved them

prune_resolved: Remove stale content.
  - Delete ◌ lines that have a matching >> answer
  - Delete ↛ lines older than 30 days if a → replacement exists
  - Never delete ⚡ or ⊕ lines
"""


def get_prompt() -> str:
    return PROMPT