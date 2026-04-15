"""
MemR Snapshot Loader — filters and loads snapshots with token budget enforcement.

The key difference from naive loading: this stops adding snapshots once the
token budget is exhausted, so the context window never overflows.
"""

from __future__ import annotations
import json
from pathlib import Path
from typing import Optional

from memr.types import SnapshotMeta, Snapshot, LoadResult
from memr.tokens.counter import count_tokens


class SnapshotLoader:
    def __init__(self, vault_name: str, snapshots_dir: Path):
        self.vault_name = vault_name
        self.snapshots_dir = snapshots_dir

    async def load(
        self,
        filter_type: str,
        value: Optional[str] = None,
        max_tokens: int = 3000,
    ) -> LoadResult:
        """Route to the right filter, then hydrate with budget."""

        all_metas = await self.list_all()

        match filter_type:
            case "recent":
                if value in ("budget", "all", "max"):
                    filtered = all_metas
                else:
                    count = int(value) if value else 3
                    filtered = all_metas[:count]
            case "topic":
                if not value:
                    raise ValueError("value (topic keyword) required for filter=topic")
                kw = value.lower()
                filtered = [
                    s for s in all_metas
                    if kw in s.topic.lower() or kw in s.file.lower()
                ]
            case "date":
                if not value:
                    raise ValueError("value (YYYY-MM-DD) required for filter=date")
                filtered = [s for s in all_metas if s.date == value]
            case "surprises":
                filtered = [s for s in all_metas if s.has_surprises]
            case "open":
                filtered = [s for s in all_metas if s.has_open]
            case "abandoned":
                filtered = [s for s in all_metas if s.has_abandoned]
            case "constraints":
                filtered = [s for s in all_metas if s.has_context]
            case _:
                raise ValueError(
                    f"Unknown filter: {filter_type}. "
                    "Use: recent, topic, date, surprises, open, abandoned, constraints"
                )

        return await self._hydrate(filtered, max_tokens)

    async def list_all(self) -> list[SnapshotMeta]:
        """Return all snapshot metadata from the index (no file reads)."""
        index = self._read_index()
        return [SnapshotMeta(**s) for s in index.get("snapshots", [])]

    async def get_summary(self) -> dict:
        """Lightweight vault summary — costs ~50-100 tokens to inject."""
        all_metas = await self.list_all()

        if not all_metas:
            return {
                "total_snapshots": 0,
                "total_tokens": 0,
                "date_range": None,
                "topics": [],
                "surprise_count": 0,
                "abandoned_count": 0,
                "open_count": 0,
            }

        dates = sorted(s.date for s in all_metas)
        return {
            "total_snapshots": len(all_metas),
            "total_tokens": sum(s.token_count for s in all_metas),
            "date_range": {"earliest": dates[0], "latest": dates[-1]},
            "topics": list({s.topic for s in all_metas}),
            "surprise_count": sum(1 for s in all_metas if s.has_surprises),
            "abandoned_count": sum(1 for s in all_metas if s.has_abandoned),
            "open_count": sum(1 for s in all_metas if s.has_open),
        }


    async def _hydrate(
        self, metas: list[SnapshotMeta], max_tokens: int
    ) -> LoadResult:
        """
        Load snapshot contents one by one, stopping when the token budget
        would be exceeded. This is the core mechanism that prevents context
        window overflow.
        """
        snapshots: list[Snapshot] = []
        tokens_used = 0
        truncated_by_budget = False
        snapshots_omitted = 0
        next_snapshot_min_tokens: int | None = None

        for i, meta in enumerate(metas):

            if meta.token_count > 0 and tokens_used + meta.token_count > max_tokens:
                truncated_by_budget = True
                snapshots_omitted = len(metas) - i
                next_snapshot_min_tokens = tokens_used + meta.token_count
                break

            content = self._read_snap_file(meta.file)
            if content is None:
                continue

            actual_tokens = meta.token_count or count_tokens(content)

            if tokens_used + actual_tokens > max_tokens:
                truncated_by_budget = True
                snapshots_omitted = len(metas) - i
                next_snapshot_min_tokens = tokens_used + actual_tokens
                break

            snapshots.append(Snapshot(meta=meta, content=content))
            tokens_used += actual_tokens

        return LoadResult(
            snapshots=snapshots,
            total_tokens=tokens_used,
            truncated_by_budget=truncated_by_budget,
            snapshots_omitted=snapshots_omitted,
            next_snapshot_min_tokens=next_snapshot_min_tokens,
        )

    def _read_index(self) -> dict:
        index_path = self.snapshots_dir / "index.json"
        try:
            return json.loads(index_path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            return {"snapshots": []}

    def _read_snap_file(self, filename: str) -> Optional[str]:
        filepath = self.snapshots_dir / filename
        try:
            return filepath.read_text(encoding="utf-8")
        except FileNotFoundError:
            return None