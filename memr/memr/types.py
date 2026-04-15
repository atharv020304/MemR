"""
MemR — Core types and data models.

Signal Markers (Decision Notation):
  →   decided and shipped (direction chosen)
  ↛   explored and abandoned (dead end + reason)
  ⚡  surprise / non-obvious finding / trap
  ◌   open thread (unresolved, parked, deferred)
  Δ   code delta (file changed, with path)
  ⊕   context gained (external constraint: legal, ops, team)
  ??  question that came up
  >>  answer / resolution
"""

from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional
from datetime import datetime


# ── Signal Markers ───────────────────────────────────────────────────────────

class Signal(str, Enum):
    """Each signal type tells the next agent what kind of knowledge a line carries."""
    DECIDED   = "→"
    ABANDONED = "↛"
    SURPRISE  = "⚡"
    OPEN      = "◌"
    DELTA     = "Δ"
    CONTEXT   = "⊕"
    QUESTION  = "??"
    ANSWER    = ">>"


SIGNAL_PATTERNS: dict[Signal, str] = {
    Signal.DECIDED:   r"^→\s",
    Signal.ABANDONED: r"^↛\s",
    Signal.SURPRISE:  r"^⚡\s?",
    Signal.OPEN:      r"^◌\s",
    Signal.DELTA:     r"^Δ\s",
    Signal.CONTEXT:   r"^⊕\s",
    Signal.QUESTION:  r"^\?\?\s",
    Signal.ANSWER:    r"^>>\s",
}


# ── Session Modes ────────────────────────────────────────────────────────────

class SessionMode(str, Enum):
    CREATE = "create"
    LOAD   = "load"     # read-only — all writes blocked
    EDIT   = "edit"     # read + write


# ── Vault ────────────────────────────────────────────────────────────────────

@dataclass
class Vault:
    """An isolated knowledge container for a project, service, or feature."""
    name: str
    path: str
    description: Optional[str] = None
    created: Optional[str] = None
    updated: Optional[str] = None


# ── Snapshot Metadata ────────────────────────────────────────────────────────

@dataclass
class SnapshotMeta:
    """Index entry for a single .snap file — no content, just metadata."""
    file: str
    date: str
    time: str
    vault: str
    topic: str
    token_count: int = 0
    has_abandoned: bool = False    # ↛ lines present
    has_surprises: bool = False    # ⚡ lines present
    has_open: bool = False         # ◌ lines present
    has_context: bool = False      # ⊕ lines present


@dataclass
class Snapshot:
    """A fully loaded snapshot: metadata + content."""
    meta: SnapshotMeta
    content: str


@dataclass
class LoadResult:
    """What comes back from a filtered snapshot load."""
    snapshots: list[Snapshot] = field(default_factory=list)
    total_tokens: int = 0
    # True when more snapshots matched the filter but were not loaded because of max_tokens.
    truncated_by_budget: bool = False
    snapshots_omitted: int = 0
    # Minimum max_tokens that would have been needed to include the first snapshot that did not fit.
    next_snapshot_min_tokens: Optional[int] = None


# ── Vault Config ─────────────────────────────────────────────────────────────

@dataclass
class VaultConfig:
    """Runtime config scoped to a specific vault."""
    memory_root: str             # Root dir for all vaults (.memr/)
    vault_name: Optional[str] = None
    vault_path: Optional[str] = None   # Computed: memory_root/vaults/<name>


# ── Lens Identifiers ─────────────────────────────────────────────────────────

class Lens(str, Enum):
    """Scoped prompt templates — only the relevant one loads per tool call."""
    RECALL  = "recall"     # read snapshots, interpret signals
    CAPTURE = "capture"    # write new snapshot using DN format
    SEARCH  = "search"     # cross-vault filtered queries
    COMPACT = "compact"    # merge / prune old snapshots


# ── Token Budget ─────────────────────────────────────────────────────────────

@dataclass
class TokenBudget:
    """Tracks token spend across a session."""
    limit: int = 3000           # max tokens from memory per call
    used: int = 0
    
    @property
    def remaining(self) -> int:
        return max(0, self.limit - self.used)
    
    def can_afford(self, cost: int) -> bool:
        return cost <= self.remaining
    
    def spend(self, cost: int) -> None:
        self.used += cost