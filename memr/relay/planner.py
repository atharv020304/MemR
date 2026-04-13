"""
═══════════════════════════════════════════════════════════════
memr/relay/planner.py — Query analysis and vault routing
═══════════════════════════════════════════════════════════════

Analyzes an incoming query to determine which vault(s) to consult
and what filter strategy to use. This is the "Think" step of the
ReAct loop — it runs before any MCP tool call.
"""

from __future__ import annotations
from dataclasses import dataclass
from typing import Optional

from memr.types import Lens


@dataclass
class QueryPlan:
    """The planner's output: what to load and how."""
    vault: str
    lens: Lens
    filter_type: str            # recent, topic, surprises, etc.
    filter_value: Optional[str] # keyword, count, date
    priority: float = 1.0       # 0-1 relevance score for multi-vault ranking


class QueryPlanner:
    """
    Analyzes user queries and plans memory retrieval strategy.
    
    The planner uses keyword heuristics to decide:
    - Which filter type to use (recent vs. topic vs. surprises, etc.)
    - Which lens to activate
    - Whether a cross-vault search is needed
    """

    # Keywords that suggest specific filter types
    SURPRISE_KEYWORDS = {"bug", "gotcha", "trap", "surprise", "weird", "broke", "fail"}
    OPEN_KEYWORDS = {"todo", "open", "unresolved", "pending", "deferred", "parked"}
    ABANDONED_KEYWORDS = {"tried", "rejected", "abandoned", "didn't work", "dead end"}
    CONSTRAINT_KEYWORDS = {"legal", "compliance", "constraint", "requirement", "mandate"}
    SAVE_KEYWORDS = {"save", "checkpoint", "wrap up", "end session", "done", "finish"}
    COMPACT_KEYWORDS = {"compact", "merge", "prune", "clean up", "tidy"}

    def plan(
        self,
        query: str,
        available_vaults: list[str],
        selected_vault: str | None = None,
    ) -> QueryPlan:
        """Analyze a query and produce a retrieval plan."""
        q = query.lower()
        vault = selected_vault or (available_vaults[0] if available_vaults else "default")

        # Save intent → capture lens, no loading needed
        if self._matches(q, self.SAVE_KEYWORDS):
            return QueryPlan(
                vault=vault, lens=Lens.CAPTURE,
                filter_type="recent", filter_value="0",
            )

        # Compact intent
        if self._matches(q, self.COMPACT_KEYWORDS):
            return QueryPlan(
                vault=vault, lens=Lens.COMPACT,
                filter_type="recent", filter_value="5",
            )

        # Surprise/gotcha intent → filter for ⚡ lines
        if self._matches(q, self.SURPRISE_KEYWORDS):
            return QueryPlan(
                vault=vault, lens=Lens.RECALL,
                filter_type="surprises", filter_value=None,
            )

        # Open threads intent
        if self._matches(q, self.OPEN_KEYWORDS):
            return QueryPlan(
                vault=vault, lens=Lens.RECALL,
                filter_type="open", filter_value=None,
            )

        # Abandoned/rejection intent
        if self._matches(q, self.ABANDONED_KEYWORDS):
            return QueryPlan(
                vault=vault, lens=Lens.RECALL,
                filter_type="abandoned", filter_value=None,
            )

        # Constraint intent
        if self._matches(q, self.CONSTRAINT_KEYWORDS):
            return QueryPlan(
                vault=vault, lens=Lens.RECALL,
                filter_type="constraints", filter_value=None,
            )

        # Topic-specific query → search by keyword
        topic_kw = self._extract_topic_keyword(q, available_vaults)
        if topic_kw:
            return QueryPlan(
                vault=vault, lens=Lens.SEARCH,
                filter_type="topic", filter_value=topic_kw,
            )

        # Default: load recent snapshots
        return QueryPlan(
            vault=vault, lens=Lens.RECALL,
            filter_type="recent", filter_value="3",
        )

    def _matches(self, query: str, keywords: set[str]) -> bool:
        return any(kw in query for kw in keywords)

    def _extract_topic_keyword(
        self, query: str, vaults: list[str]
    ) -> str | None:
        """
        Try to extract a meaningful topic keyword from the query.
        Filters out common stop words and vault names.
        """
        stop_words = {
            "what", "how", "why", "when", "where", "did", "do", "does",
            "is", "are", "was", "were", "the", "a", "an", "about",
            "tell", "me", "show", "find", "get", "load", "we", "our",
            "i", "my", "this", "that", "with", "for", "and", "or",
        }
        vault_words = {w.lower() for v in vaults for w in v.split("-")}

        words = query.split()
        candidates = [
            w for w in words
            if w.lower() not in stop_words
            and w.lower() not in vault_words
            and len(w) > 2
        ]

        return candidates[0] if candidates else None

