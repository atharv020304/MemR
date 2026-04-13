# ═══════════════════════════════════════════════════════════════
# FILE: memr/lens/capture.py
# ═══════════════════════════════════════════════════════════════
"""Capture lens — saving session snapshots with Decision Notation."""

PROMPT = """\
You are saving a session snapshot to MemR shared memory. Use Decision Notation:

→  decided/shipped [over: rejected-alt | reason: why]
↛  explored but abandoned [reason: why | replaced: what-worked]
⚡ surprise / non-obvious finding / trap that others should know
◌  open thread — unresolved or deferred [context: why deferred]
Δ  code delta → path/to/file.py (what changed)
⊕  external constraint shaping decisions (legal, client, ops, team)
?? question with a non-obvious answer
>> the answer / resolution

RULES:
- ONLY save what cannot be recovered by reading the code
- DO NOT save implementation details derivable from source files
- Focus on: decisions (and why), rejected alternatives (and why),
  surprises, constraints, and unresolved questions
- Keep each line to ONE signal + ONE fact. Be terse.
"""


def get_prompt() -> str:
    return PROMPT