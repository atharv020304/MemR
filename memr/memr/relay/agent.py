"""
MemR Relay — ReAct routing agent.

Sits on top of the MCP server and decides:
  1. Which vault(s) to query
  2. Which lens (scoped prompt) to load
  3. How much token budget to allocate
  4. Whether to skip the call entirely (context already loaded)

The Relay runs an Observe → Think → Act loop for every incoming request
before any MCP tool gets called.
"""

from __future__ import annotations
import logging
from dataclasses import dataclass, field
from typing import Any

from memr.types import Lens, TokenBudget, SessionMode
from memr.lens.registry import LensRegistry
from memr.tokens.counter import count_tokens
from memr.trace.emitter import TraceEmitter, NullEmitter

logger = logging.getLogger("memr.relay")


@dataclass
class Observation:
    """What the relay sees before making a decision."""
    user_query: str
    current_context_tokens: int       # tokens already in the conversation
    available_vaults: list[str]
    selected_vault: str | None
    session_mode: SessionMode | None
    already_loaded_topics: list[str]  # topics already in context window


@dataclass
class Thought:
    """The relay's reasoning about what to do."""
    target_vault: str | None
    lens: Lens
    token_budget: int
    skip_load: bool = False           # if context already covers this
    reason: str = ""


@dataclass
class Action:
    """What the relay decides to execute."""
    tool_name: str
    arguments: dict[str, Any]
    lens_prompt: str                  # the scoped system prompt to inject
    estimated_tokens: int


class Relay:
    """
    The ReAct routing agent. Call .plan() with an observation
    to get back a planned action (or a skip signal).
    """

    def __init__(
        self,
        budget: TokenBudget | None = None,
        tracer: TraceEmitter | None = None,
    ):
        self.budget = budget or TokenBudget()
        self.lenses = LensRegistry()
        self.tracer = tracer or NullEmitter()
        self._loaded_topics: set[str] = set()

    def plan(self, obs: Observation) -> Thought:
        """
        Observe → Think: analyze the request and decide what to do.
        This runs BEFORE any MCP tool call.
        """
        with self.tracer.span("relay_plan", query=obs.user_query) as span:

            # ── Check if we can skip ─────────────────────────────────
            query_lower = obs.user_query.lower()
            for topic in obs.already_loaded_topics:
                if topic.lower() in query_lower:
                    thought = Thought(
                        target_vault=obs.selected_vault,
                        lens=Lens.RECALL,
                        token_budget=0,
                        skip_load=True,
                        reason=f'Topic "{topic}" already in context — skipping load',
                    )
                    span.set_metadata(decision="skip", reason=thought.reason)
                    return thought

            # ── Decide lens ──────────────────────────────────────────
            lens = self._pick_lens(obs)

            lens_cost = count_tokens(self.lenses.get(lens))
            overhead = 500  # estimated response tokens
            available = self.budget.remaining - lens_cost - overhead
            token_budget = max(500, min(available, 3000))

            thought = Thought(
                target_vault=obs.selected_vault,
                lens=lens,
                token_budget=token_budget,
                reason=f"Using {lens.value} lens with {token_budget} token budget",
            )

            span.set_metadata(
                decision="load",
                lens=lens.value,
                budget=token_budget,
                vault=obs.selected_vault,
            )
            return thought

    def act(self, thought: Thought) -> Action | None:
        """
        Think → Act: turn the thought into a concrete MCP tool call.
        Returns None if the thought says to skip.
        """
        if thought.skip_load:
            logger.info(f"Relay: skipping — {thought.reason}")
            return None

        lens_prompt = self.lenses.get(thought.lens)
        lens_tokens = count_tokens(lens_prompt)

        # Route to the right tool based on lens
        match thought.lens:
            case Lens.RECALL:
                return Action(
                    tool_name="memr_load_snapshots",
                    arguments={
                        "vault": thought.target_vault,
                        "filter": "recent",
                        "value": "3",
                        "token_budget": thought.token_budget,
                    },
                    lens_prompt=lens_prompt,
                    estimated_tokens=thought.token_budget + lens_tokens,
                )
            case Lens.CAPTURE:
                return Action(
                    tool_name="memr_save_snapshot",
                    arguments={"vault": thought.target_vault},
                    lens_prompt=lens_prompt,
                    estimated_tokens=lens_tokens,
                )
            case Lens.SEARCH:
                return Action(
                    tool_name="memr_load_snapshots",
                    arguments={
                        "vault": thought.target_vault,
                        "filter": "topic",
                        "token_budget": thought.token_budget,
                    },
                    lens_prompt=lens_prompt,
                    estimated_tokens=thought.token_budget + lens_tokens,
                )
            case Lens.COMPACT:
                return Action(
                    tool_name="memr_compact",
                    arguments={
                        "vault": thought.target_vault,
                        "strategy": "merge_recent",
                    },
                    lens_prompt=lens_prompt,
                    estimated_tokens=lens_tokens,
                )

    def record_loaded(self, topic: str) -> None:
        """Track what's been loaded so we can skip redundant calls."""
        self._loaded_topics.add(topic)

    def _pick_lens(self, obs: Observation) -> Lens:
        """Heuristic lens selection based on the query shape."""
        q = obs.user_query.lower()

        if obs.session_mode == SessionMode.LOAD:
            return Lens.RECALL

        # Save-intent keywords
        if any(kw in q for kw in ["save", "checkpoint", "wrap up", "end session"]):
            return Lens.CAPTURE

        # Search-intent keywords
        if any(kw in q for kw in ["find", "search", "when did", "which session"]):
            return Lens.SEARCH

        # Compact-intent keywords
        if any(kw in q for kw in ["compact", "merge", "clean up", "prune"]):
            return Lens.COMPACT

        # Default: recall
        return Lens.RECALL