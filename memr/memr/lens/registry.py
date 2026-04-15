"""
MemR Lens Registry — maps each lens to its scoped system prompt.

Each lens is defined in its own module (recall.py, capture.py, etc.)
and registered here. The registry is the single lookup point used
by the Relay agent to fetch the right prompt before a tool call.
"""

from memr.types import Lens
from memr.lens import recall, capture, search, compact


class LensRegistry:
    """Maps lens names to their scoped prompt templates."""

    _prompts: dict[Lens, str] = {
        Lens.RECALL:  recall.PROMPT,
        Lens.CAPTURE: capture.PROMPT,
        Lens.SEARCH:  search.PROMPT,
        Lens.COMPACT: compact.PROMPT,
    }

    def get(self, lens: Lens) -> str:
        """Get the scoped system prompt for this lens."""
        return self._prompts[lens]

    def token_cost(self, lens: Lens) -> int:
        """Approximate token cost of injecting this lens."""
        from memr.tokens.counter import count_tokens
        return count_tokens(self._prompts[lens])

    def all_lenses(self) -> list[Lens]:
        """List all registered lenses."""
        return list(self._prompts.keys())

    def total_cost(self) -> int:
        """Total tokens if all lenses were loaded (the old monolithic way)."""
        from memr.tokens.counter import count_tokens
        return sum(count_tokens(p) for p in self._prompts.values())

    def savings_per_call(self, active_lens: Lens) -> int:
        """Tokens saved by loading only one lens instead of all."""
        return self.total_cost() - self.token_cost(active_lens)