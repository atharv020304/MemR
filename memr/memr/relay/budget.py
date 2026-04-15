
"""
═══════════════════════════════════════════════════════════════
memr/relay/budget.py — Session-wide token budget tracking
═══════════════════════════════════════════════════════════════

Tracks cumulative token consumption across an entire session,
not just a single tool call. This prevents the context window
from gradually filling up over many small loads.
"""

from __future__ import annotations
import logging
from dataclasses import dataclass, field
from typing import Any

from memr.tokens.counter import count_tokens
from memr.trace.emitter import TraceEmitter, NullEmitter

logger = logging.getLogger("memr.budget")


@dataclass
class SpendRecord:
    """One entry in the token spend log."""
    tool: str
    vault: str
    tokens: int
    description: str


class BudgetTracker:
    """
    Session-wide token budget manager.

    Tracks how many tokens have been consumed from memory across
    all tool calls in a session. Provides per-call budgets that
    account for what's already been spent.

    Usage:
        tracker = BudgetTracker(session_limit=8000)
        per_call = tracker.allocate("memr_load_snapshots", "auth-service")
        # per_call might be 4000 if nothing spent yet, or 1500 if 6500 already used
    """

    def __init__(
        self,
        session_limit: int = 8000,
        per_call_max: int = 4000,
        reserve: int = 1000,
        tracer: TraceEmitter | None = None,
    ):
        self.session_limit = session_limit
        self.per_call_max = per_call_max
        self.reserve = reserve           # keep this many tokens free for agent response
        self.tracer = tracer or NullEmitter()

        self._spent: int = 0
        self._log: list[SpendRecord] = []

    @property
    def remaining(self) -> int:
        return max(0, self.session_limit - self._spent - self.reserve)

    @property
    def spent(self) -> int:
        return self._spent

    def allocate(self, tool: str, vault: str) -> int:
        """
        Compute how many tokens this tool call is allowed to consume.
        Returns the budget for this specific call.
        """
        available = self.remaining
        budget = min(available, self.per_call_max)

        if budget < 200:
            logger.warning(
                f"Low budget: {budget} tokens remaining for {tool} on {vault}. "
                f"Session has consumed {self._spent}/{self.session_limit} tokens."
            )

        return budget

    def record(self, tool: str, vault: str, tokens: int, desc: str = "") -> None:
        """Record actual token consumption after a tool call completes."""
        self._spent += tokens
        record = SpendRecord(tool=tool, vault=vault, tokens=tokens, description=desc)
        self._log.append(record)

        with self.tracer.span("budget_spend", tool=tool, vault=vault, tokens=tokens):
            pass

        logger.debug(
            f"Budget: spent {tokens} on {tool}/{vault}. "
            f"Total: {self._spent}/{self.session_limit} ({self.remaining} remaining)"
        )

    def get_report(self) -> dict[str, Any]:
        """Full spending report for the session."""
        return {
            "session_limit": self.session_limit,
            "total_spent": self._spent,
            "remaining": self.remaining,
            "calls": [
                {
                    "tool": r.tool,
                    "vault": r.vault,
                    "tokens": r.tokens,
                    "description": r.description,
                }
                for r in self._log
            ],
        }

    def reset(self) -> None:
        """Reset for a new session."""
        self._spent = 0
        self._log.clear()