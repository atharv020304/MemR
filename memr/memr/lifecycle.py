"""
Session-scoped helpers for MemR — **not** a second storage format.

Everything here ultimately uses the same code paths as the manual MCP tools:

  * ``ensure_loaded`` → ``VaultContext.loader`` → same as ``memr_load_snapshots``
    with ``filter=recent`` and a token budget (``value="budget"``).
  * ``maybe_save`` → ``VaultContext.writer.save_merged`` → same persistence as
    ``memr_save_snapshot`` (merged into today's file when applicable).

The **SessionBuffer** + ``track_*`` APIs exist only for ``memr_track`` / ``memr_checkpoint``:
they collect Decision Notation lines and flush them through ``maybe_save``. If you only
use ``memr_load_snapshots`` and ``memr_save_snapshot``, you can ignore the buffer; the
server still uses ``ensure_loaded`` so the vault is warm before other tools run.
"""

from __future__ import annotations
import logging
import re
from datetime import datetime
from typing import Optional

from memr.types import Signal, SessionMode, SnapshotMeta
from memr.vault.manager import VaultManager
from memr.vault.auto import AutoProvisioner
from memr.vault.context import VaultContext
from memr.snapshot.parser import SignalParser
from memr.tokens.counter import count_tokens
from memr.trace.emitter import TraceEmitter, NullEmitter

SNAPSHOT_SECTION_JOIN = "\n\n───────────────────────\n\n"

logger = logging.getLogger("memr.session_memory")


class SessionBuffer:
    """
    Collects notable events during a session.
    When enough accumulates, it's ready to be saved as a snapshot.
    """

    def __init__(self):
        self.decisions: list[str] = []       # → lines
        self.abandoned: list[str] = []       # ↛ lines
        self.surprises: list[str] = []       # ⚡ lines
        self.open_threads: list[str] = []    # ◌ lines
        self.deltas: list[str] = []          # Δ lines
        self.constraints: list[str] = []     # ⊕ lines
        self.questions: list[str] = []       # ?? lines
        self.answers: list[str] = []         # >> lines
        self.topics: set[str] = set()
        self._dirty = False

    def add(self, signal: Signal, content: str) -> None:
        """Add a knowledge item to the buffer."""
        match signal:
            case Signal.DECIDED:   self.decisions.append(f"→ {content}")
            case Signal.ABANDONED: self.abandoned.append(f"↛ {content}")
            case Signal.SURPRISE:  self.surprises.append(f"⚡ {content}")
            case Signal.OPEN:      self.open_threads.append(f"◌ {content}")
            case Signal.DELTA:     self.deltas.append(f"Δ {content}")
            case Signal.CONTEXT:   self.constraints.append(f"⊕ {content}")
            case Signal.QUESTION:  self.questions.append(f"?? {content}")
            case Signal.ANSWER:    self.answers.append(f">> {content}")
        self._dirty = True

    def add_topic(self, topic: str) -> None:
        self.topics.add(topic)

    @property
    def is_worth_saving(self) -> bool:
        """Save after any substantive signal — including a single Δ or ◌ line."""
        meaningful = (
            len(self.decisions)
            + len(self.surprises)
            + len(self.abandoned)
            + len(self.constraints)
            + len(self.deltas)
            + len(self.open_threads)
        )
        if meaningful >= 1:
            return True
        # QA pair (both halves from one memr_track qa call)
        if len(self.questions) >= 1 and len(self.answers) >= 1:
            return True
        total = (
            len(self.decisions)
            + len(self.abandoned)
            + len(self.surprises)
            + len(self.open_threads)
            + len(self.deltas)
            + len(self.constraints)
            + len(self.questions)
            + len(self.answers)
        )
        return total >= 2

    @property
    def is_dirty(self) -> bool:
        return self._dirty

    def to_content(self) -> str:
        """Render buffer as Decision Notation content."""
        lines: list[str] = []
        lines.extend(self.decisions)
        lines.extend(self.abandoned)
        lines.extend(self.surprises)
        lines.extend(self.open_threads)
        lines.extend(self.deltas)
        lines.extend(self.constraints)
        lines.extend(self.questions)
        lines.extend(self.answers)
        return "\n".join(lines)

    def to_topic(self) -> str:
        """Generate a topic string from accumulated topics."""
        if self.topics:
            return ", ".join(sorted(self.topics)[:3])
        if self.decisions:
            # Extract first decision as topic
            first = self.decisions[0].replace("→ ", "")
            return first[:50]
        return f"session {datetime.now().strftime('%Y-%m-%d %H:%M')}"

    def clear(self) -> None:
        self.decisions.clear()
        self.abandoned.clear()
        self.surprises.clear()
        self.open_threads.clear()
        self.deltas.clear()
        self.constraints.clear()
        self.questions.clear()
        self.answers.clear()
        self.topics.clear()
        self._dirty = False


class SessionMemory:
    """
    When to warm-read and when to flush the **track** buffer.

    **Load:** ``ensure_loaded`` uses ``SnapshotLoader`` — identical stack to
    ``memr_load_snapshots``. Call it once per MCP process (or per vault switch);
    the server also invokes it before most MemR tools (see ``MemRServer._dispatch``).

    **Save:** ``maybe_save`` uses ``SnapshotWriter.save_merged`` — same writer family
    as ``memr_save_snapshot``. It only runs for buffered ``memr_track`` data unless
    you call ``memr_checkpoint`` / ``maybe_save(force=True)``.
    """

    def __init__(
        self,
        vault_mgr: VaultManager,
        tracer: TraceEmitter | None = None,
    ):
        self.vault_mgr = vault_mgr
        self.auto = AutoProvisioner(vault_mgr)
        self.tracer = tracer or NullEmitter()
        self.parser = SignalParser()

        self._buffer = SessionBuffer()
        self._loaded_vault: str | None = None
        self._loaded_topics: set[str] = set()
        self._loaded_files: set[str] = set()
        self._session_started = False
        self._contexts: dict[str, VaultContext] = {}

    def _get_context(self, vault_name: str) -> VaultContext:
        if vault_name not in self._contexts:
            self._contexts[vault_name] = VaultContext(
                str(self.vault_mgr.memory_root), vault_name
            )
        return self._contexts[vault_name]

    # ── Auto-Load ────────────────────────────────────────────────

    async def ensure_loaded(
        self, vault_name: str | None = None, max_tokens: int = 3000
    ) -> dict | None:
        """
        Same snapshot read path as ``memr_load_snapshots`` (recent + token budget).

        Returns a content dict on first load for this vault in this MCP session,
        or ``None`` if this vault was already warmed (cheap no-op).
        """
        vault = await self.auto.ensure_vault(vault_name)

        # Already loaded this vault — skip
        if vault == self._loaded_vault and self._session_started:
            return None

        ctx = self._get_context(vault)

        if vault != self._loaded_vault:
            self._loaded_topics.clear()
            self._loaded_files.clear()

        with self.tracer.span("auto_load", vault=vault) as span:
            # Fill token budget with newest snapshots — not a hard count of 3.
            result = await ctx.loader.load("recent", "budget", max_tokens=max_tokens)
            span.set_metadata(
                snapshots_loaded=len(result.snapshots),
                tokens_used=result.total_tokens,
                truncated_by_budget=result.truncated_by_budget,
            )

        self._loaded_vault = vault
        self._session_started = True

        for snap in result.snapshots:
            self._loaded_topics.add(snap.meta.topic.lower())
            self._loaded_files.add(snap.meta.file)

        logger.info(
            f"Auto-loaded {len(result.snapshots)} snapshots "
            f"({result.total_tokens} tk) from vault '{vault}'"
        )

        combined = SNAPSHOT_SECTION_JOIN.join(s.content for s in result.snapshots)

        out: dict = {
            "vault": vault,
            "snapshots_loaded": len(result.snapshots),
            "total_tokens": result.total_tokens,
            "content": combined,
            "snapshot_files": [s.meta.file for s in result.snapshots],
        }
        if result.truncated_by_budget:
            out["truncated_by_budget"] = True
            out["snapshots_omitted"] = result.snapshots_omitted
            out["next_snapshot_min_tokens"] = result.next_snapshot_min_tokens
        return out

    def invalidate_load_cache(self) -> None:
        """Next ensure_loaded / memr_auto_context will reload from disk (same MCP session)."""
        self._session_started = False
        self._loaded_vault = None
        self._loaded_topics.clear()
        self._loaded_files.clear()

    # ── Collect Knowledge During Session ─────────────────────────

    def track_decision(self, content: str, topic: str | None = None) -> None:
        """Called when the AI makes or reports a decision."""
        self._buffer.add(Signal.DECIDED, content)
        if topic:
            self._buffer.add_topic(topic)

    def track_surprise(self, content: str) -> None:
        """Called when the AI discovers something non-obvious."""
        self._buffer.add(Signal.SURPRISE, content)

    def track_abandoned(self, content: str) -> None:
        """Called when an approach is tried and rejected."""
        self._buffer.add(Signal.ABANDONED, content)

    def track_delta(self, filepath: str, description: str = "") -> None:
        """Called when a file is modified."""
        msg = f"{filepath} — {description}" if description else filepath
        self._buffer.add(Signal.DELTA, msg)

    def track_open(self, content: str) -> None:
        """Called when something is left unresolved."""
        self._buffer.add(Signal.OPEN, content)

    def track_constraint(self, content: str) -> None:
        """Called when an external constraint is discovered."""
        self._buffer.add(Signal.CONTEXT, content)

    def track_qa(self, question: str, answer: str) -> None:
        """Called when a question gets a non-obvious answer."""
        self._buffer.add(Signal.QUESTION, question)
        self._buffer.add(Signal.ANSWER, answer)

    def ingest_ai_response(self, response_text: str) -> None:
        """
        Scan an AI response for notable patterns and auto-collect them.
        This is the magic — the AI doesn't need to explicitly call
        track_* methods. We parse its response for signals.
        """
        # Look for decision patterns
        decision_patterns = [
            r"(?:I'll|let's|we should|going to|choosing|using|switched to)\s+(.+?)(?:\.|$)",
            r"(?:decided on|went with|picked|selected)\s+(.+?)(?:\.|$)",
        ]
        for pat in decision_patterns:
            for match in re.finditer(pat, response_text, re.IGNORECASE):
                self._buffer.add(Signal.DECIDED, match.group(0).strip()[:100])

        # Look for warning/gotcha patterns
        surprise_patterns = [
            r"(?:watch out|careful|gotcha|warning|note that|important:)\s+(.+?)(?:\.|$)",
            r"(?:bug|issue|problem):\s+(.+?)(?:\.|$)",
        ]
        for pat in surprise_patterns:
            for match in re.finditer(pat, response_text, re.IGNORECASE):
                self._buffer.add(Signal.SURPRISE, match.group(0).strip()[:100])

        # Look for file changes
        file_patterns = [
            r"(?:created|modified|updated|edited|changed)\s+([\w/\\]+\.\w+)",
        ]
        for pat in file_patterns:
            for match in re.finditer(pat, response_text, re.IGNORECASE):
                self._buffer.add(Signal.DELTA, match.group(1))

    # ── Auto-Save ────────────────────────────────────────────────

    async def maybe_save(self, force: bool = False) -> SnapshotMeta | None:
        """
        Flush ``memr_track`` buffer via ``SnapshotWriter.save_merged`` — same writer
        as ``memr_save_snapshot``. Returns ``None`` if the buffer is empty or below
        threshold (unless ``force``).
        """
        if not force and not self._buffer.is_worth_saving:
            return None

        if not self._buffer.is_dirty:
            return None

        vault = self._loaded_vault
        if not vault:
            vault = await self.auto.ensure_vault()

        ctx = self._get_context(vault)
        topic = self._buffer.to_topic()
        content = self._buffer.to_content()

        with self.tracer.span("auto_save", vault=vault, topic=topic) as span:
            meta = await ctx.writer.save_merged(topic, content)
            span.set_metadata(token_count=meta.token_count)

        logger.info(
            f"Auto-saved snapshot: {meta.file} "
            f"({meta.token_count} tk) to vault '{vault}'"
        )

        self._buffer.clear()
        return meta

    async def end_session(self) -> SnapshotMeta | None:
        """
        Called when the session is ending. Saves if there's anything
        worth keeping, even if the threshold isn't met.
        """
        if self._buffer.is_dirty:
            return await self.maybe_save(force=True)
        return None

    def detect_session_end(self, user_message: str) -> bool:
        """Check if the user's message signals session end."""
        end_signals = {
            "bye", "done", "thanks", "that's all", "wrap up",
            "end session", "goodbye", "finish", "stop",
            "that's it", "all good", "cheers",
        }
        msg = user_message.lower().strip()
        return any(signal in msg for signal in end_signals)

    # ── Status ───────────────────────────────────────────────────

    def get_status(self) -> dict:
        return {
            "session_started": self._session_started,
            "loaded_vault": self._loaded_vault,
            "loaded_topics": sorted(self._loaded_topics),
            "buffer_items": {
                "decisions": len(self._buffer.decisions),
                "surprises": len(self._buffer.surprises),
                "abandoned": len(self._buffer.abandoned),
                "open_threads": len(self._buffer.open_threads),
                "deltas": len(self._buffer.deltas),
                "constraints": len(self._buffer.constraints),
            },
            "worth_saving": self._buffer.is_worth_saving,
        }


# Backward-compatible name (same class).
LifecycleManager = SessionMemory