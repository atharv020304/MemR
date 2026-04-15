"""
MemR Auto Tools — replaces manual mode switching with automatic behavior.

Instead of:
  memr_set_mode → memr_load_snapshots → work → memr_save_snapshot

The agent just calls:
  memr_auto_context  → (auto-loads on first call, skips on subsequent)
  memr_track         → (records decisions/surprises during work)
  memr_checkpoint    → (auto-saves if enough content accumulated)

These three tools replace the entire manual workflow.
The original tools still exist for power users who want manual control.
"""

from __future__ import annotations

AUTO_TOOLS = [
    {
        "name": "memr_auto_context",
        "description": (
            "Automatically loads relevant project memory. Call this ONCE at the "
            "start of any conversation. It auto-creates a vault if none exists, "
            "auto-loads recent snapshots, and returns compressed project knowledge. "
            "On subsequent calls in the same session, returns nothing (already loaded). "
            "You do NOT need to call memr_set_mode or memr_load_snapshots."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "vault": {
                    "type": "string",
                    "description": "Optional vault name. Auto-detected from project if omitted.",
                },
                "topic_hint": {
                    "type": "string",
                    "description": "Optional hint about what the user is working on, for smarter filtering.",
                },
            },
        },
    },
    {
        "name": "memr_track",
        "description": (
            "Record a notable event during the session. Call this whenever you "
            "make a decision, discover something surprising, reject an approach, "
            "or modify a file. These are collected and auto-saved at session end.\n\n"
            "Signal types:\n"
            "  decided   — chose an approach (include what was rejected and why)\n"
            "  surprise  — found something non-obvious, a bug, or a trap\n"
            "  abandoned — tried something that didn't work (include why)\n"
            "  delta     — modified a file\n"
            "  open      — left something unresolved for later\n"
            "  constraint— discovered an external rule (legal, team, client)\n"
            "  qa        — question with a non-obvious answer"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "signal": {
                    "type": "string",
                    "enum": [
                        "decided", "surprise", "abandoned",
                        "delta", "open", "constraint", "qa",
                    ],
                },
                "content": {
                    "type": "string",
                    "description": "What happened. Be terse — one fact per call.",
                },
                "topic": {
                    "type": "string",
                    "description": "Optional topic tag for this event.",
                },
            },
            "required": ["signal", "content"],
        },
    },
    {
        "name": "memr_checkpoint",
        "description": (
            "Save accumulated knowledge to the vault. Called automatically when "
            "enough notable events have been tracked, or when the session ends. "
            "You can also call this explicitly after completing a significant piece of work. "
            "Returns nothing if the buffer is empty or not worth saving yet."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "force": {
                    "type": "boolean",
                    "description": "Save even if threshold not met. Use at session end.",
                },
            },
        },
    },
]