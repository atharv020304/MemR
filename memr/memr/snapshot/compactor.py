"""
MemR Compactor — merge and prune old snapshots to keep vaults lean.

Two strategies:
  merge_recent  — combine N recent snapshots into one
  prune_resolved — remove stale lines from all snapshots

Rules:
  - ⚡ (surprises) are NEVER removed — traps stay forever
  - ⊕ (constraints) are NEVER removed — unless explicitly lifted
  - ◌ (open) lines are removed only when a matching >> resolves them
  - ↛ (abandoned) lines are removed when a → replacement exists
  - Duplicate → lines are deduplicated (keep the latest)
"""

from __future__ import annotations
import json
import re
from datetime import datetime, date, timedelta
from pathlib import Path
from typing import Any

from memr.types import Signal, SnapshotMeta
from memr.snapshot.parser import SignalParser, ParsedLine
from memr.tokens.counter import count_tokens


class Compactor:
    def __init__(self, vault_name: str, snapshots_dir: Path):
        self.vault_name = vault_name
        self.snapshots_dir = snapshots_dir
        self.parser = SignalParser()

    async def run(self, strategy: str, count: int = 5) -> dict[str, Any]:
        match strategy:
            case "merge_recent":
                return await self._merge_recent(count)
            case "prune_resolved":
                return await self._prune_resolved()
            case _:
                raise ValueError(f"Unknown strategy: {strategy}")

    # ── Merge Recent ─────────────────────────────────────────────────────

    async def _merge_recent(self, count: int) -> dict[str, Any]:
        """Combine the N most recent snapshots into a single snapshot."""
        index = self._read_index()
        metas = index.get("snapshots", [])[:count]

        if len(metas) < 2:
            return {"merged": False, "reason": "Need at least 2 snapshots to merge"}

        # Collect all lines from all snapshots
        all_lines: list[ParsedLine] = []
        files_to_remove: list[str] = []

        for meta in metas:
            filepath = self.snapshots_dir / meta["file"]
            if not filepath.exists():
                continue

            content = filepath.read_text(encoding="utf-8")
            body = self._extract_body(content)
            lines = self.parser.parse(body)
            all_lines.extend(lines)
            files_to_remove.append(meta["file"])

        # Deduplicate and compact
        compacted = self._deduplicate(all_lines)

        # Build merged content
        merged_body = "\n".join(line.raw for line in compacted)
        topics = [m.get("topic", "unknown") for m in metas]
        merged_topic = f"merged: {', '.join(topics[:3])}"
        if len(topics) > 3:
            merged_topic += f" +{len(topics) - 3} more"

        # Save the merged snapshot
        from memr.snapshot.writer import SnapshotWriter
        writer = SnapshotWriter(self.vault_name, self.snapshots_dir)
        new_meta = await writer.save(merged_topic, merged_body)

        # Remove old snapshot files
        for fname in files_to_remove:
            filepath = self.snapshots_dir / fname
            filepath.unlink(missing_ok=True)

        # Rebuild index without the old entries
        old_files = set(files_to_remove)
        index["snapshots"] = [
            s for s in index["snapshots"] if s["file"] not in old_files
        ]
        self._write_index(index)

        return {
            "merged": True,
            "input_snapshots": len(files_to_remove),
            "output_file": new_meta.file,
            "lines_before": len(all_lines),
            "lines_after": len(compacted),
            "tokens_saved": sum(m.get("token_count", 0) for m in metas) - new_meta.token_count,
        }

    # ── Prune Resolved ───────────────────────────────────────────────────

    async def _prune_resolved(self) -> dict[str, Any]:
        """Remove stale lines across all snapshots."""
        index = self._read_index()
        total_removed = 0
        files_modified = 0

        for meta in index.get("snapshots", []):
            filepath = self.snapshots_dir / meta["file"]
            if not filepath.exists():
                continue

            content = filepath.read_text(encoding="utf-8")
            header, body = self._split_header_body(content)
            lines = self.parser.parse(body)

            pruned = self._prune_lines(lines)
            removed = len(lines) - len(pruned)

            if removed > 0:
                new_body = "\n".join(line.raw for line in pruned)
                new_content = header + "---\n" + new_body + "\n"
                filepath.write_text(new_content, encoding="utf-8")

                meta["token_count"] = count_tokens(new_content)
                total_removed += removed
                files_modified += 1

        self._write_index(index)

        return {
            "pruned": True,
            "lines_removed": total_removed,
            "files_modified": files_modified,
        }

    # ── Deduplication Logic ──────────────────────────────────────────────

    def _deduplicate(self, lines: list[ParsedLine]) -> list[ParsedLine]:
        """
        Compact a list of parsed lines:
        - Dedup → lines by their subject (keep latest)
        - Remove ◌ lines that have a matching >> answer
        - Remove ↛ lines whose → replacement exists
        - ALWAYS keep ⚡ and ⊕ lines
        """
        result: list[ParsedLine] = []
        seen_decisions: dict[str, ParsedLine] = {}
        answers: set[str] = set()
        decided_subjects: set[str] = set()

        # First pass: collect answers and decided subjects
        for line in lines:
            if line.signal == Signal.ANSWER:
                answers.add(self._normalize_subject(line.body))
            if line.signal == Signal.DECIDED:
                decided_subjects.add(self._normalize_subject(line.body))

        # Second pass: filter and deduplicate
        for line in lines:
            subj = self._normalize_subject(line.body)

            # Always keep surprises and constraints
            if line.signal in (Signal.SURPRISE, Signal.CONTEXT):
                result.append(line)
                continue

            # Dedup decided lines — keep latest
            if line.signal == Signal.DECIDED:
                seen_decisions[subj] = line
                continue

            # Remove open threads that have answers
            if line.signal == Signal.OPEN and subj in answers:
                continue

            # Remove questions that have answers
            if line.signal == Signal.QUESTION and subj in answers:
                continue

            # Remove abandoned if a decided replacement exists
            if line.signal == Signal.ABANDONED and subj in decided_subjects:
                continue

            result.append(line)

        # Add deduplicated decisions
        result.extend(seen_decisions.values())

        return result

    def _prune_lines(self, lines: list[ParsedLine]) -> list[ParsedLine]:
        """Remove stale lines from a single snapshot."""
        answers = {
            self._normalize_subject(l.body)
            for l in lines if l.signal == Signal.ANSWER
        }
        decisions = {
            self._normalize_subject(l.body)
            for l in lines if l.signal == Signal.DECIDED
        }

        pruned: list[ParsedLine] = []
        for line in lines:
            subj = self._normalize_subject(line.body)

            # Never prune surprises or constraints
            if line.signal in (Signal.SURPRISE, Signal.CONTEXT):
                pruned.append(line)
                continue

            # Prune resolved open threads
            if line.signal == Signal.OPEN and subj in answers:
                continue

            # Prune old abandoned lines if replacement shipped
            if line.signal == Signal.ABANDONED and subj in decisions:
                continue

            pruned.append(line)

        return pruned

    # ── Helpers ──────────────────────────────────────────────────────────

    @staticmethod
    def _normalize_subject(text: str) -> str:
        """Extract a rough subject key for deduplication."""
        # Strip bracket annotations like [over: X | reason: Y]
        clean = re.sub(r"\[.*?\]", "", text).strip()
        # Lowercase and collapse whitespace
        return re.sub(r"\s+", " ", clean.lower())

    @staticmethod
    def _extract_body(content: str) -> str:
        """Get everything after the --- separator."""
        if "---" in content:
            return content.split("---", 1)[1].strip()
        return content.strip()

    @staticmethod
    def _split_header_body(content: str) -> tuple[str, str]:
        """Split into (header_with_newline, body)."""
        if "---" in content:
            parts = content.split("---", 1)
            return parts[0], parts[1].strip()
        return "", content.strip()

    def _read_index(self) -> dict:
        index_path = self.snapshots_dir / "index.json"
        try:
            return json.loads(index_path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            return {"snapshots": []}

    def _write_index(self, index: dict) -> None:
        index_path = self.snapshots_dir / "index.json"
        index_path.write_text(json.dumps(index, indent=2), encoding="utf-8")