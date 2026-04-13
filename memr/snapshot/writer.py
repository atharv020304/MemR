"""
MemR Snapshot Writer — compresses and saves .snap files with Decision Notation.
"""

from __future__ import annotations
import json
import re
from datetime import datetime
from pathlib import Path

from memr.types import SnapshotMeta, Signal
from memr.tokens.counter import count_tokens


class SnapshotWriter:
    def __init__(self, vault_name: str, snapshots_dir: Path):
        self.vault_name = vault_name
        self.snapshots_dir = snapshots_dir

    async def save(self, topic: str, content: str) -> SnapshotMeta:
        """Save a new snapshot file and update the index."""
        self.snapshots_dir.mkdir(parents=True, exist_ok=True)

        now = datetime.now()
        date_str = now.strftime("%Y-%m-%d")
        time_str = now.strftime("%H%M")
        safe_topic = self._slugify(topic)
        filename = f"{date_str}-{time_str}-{safe_topic}.snap"

        # Build snapshot with structured preamble
        header = (
            f"@vault: {self.vault_name}\n"
            f"@when: {now.isoformat(timespec='minutes')}\n"
            f"@topic: {topic}\n"
            "---\n"
        )
        full_content = header + content.strip() + "\n"

        filepath = self.snapshots_dir / filename
        filepath.write_text(full_content, encoding="utf-8")

        token_count = count_tokens(full_content)

        meta = SnapshotMeta(
            file=filename,
            date=date_str,
            time=time_str,
            vault=self.vault_name,
            topic=topic,
            token_count=token_count,
            has_abandoned=Signal.ABANDONED.value in content,
            has_surprises=Signal.SURPRISE.value in content,
            has_open=Signal.OPEN.value in content,
            has_context=Signal.CONTEXT.value in content,
        )

        # Update meta with actual token count in header
        full_with_tokens = full_content.replace(
            "---\n", f"@tokens: {token_count}\n---\n"
        )
        filepath.write_text(full_with_tokens, encoding="utf-8")

        await self._update_index(meta)
        return meta

    async def append(self, filename: str, content: str) -> None:
        """Append content to an existing snapshot (mid-session checkpoint)."""
        filepath = self.snapshots_dir / filename
        existing = filepath.read_text(encoding="utf-8")
        updated = existing.rstrip() + "\n" + content.strip() + "\n"
        filepath.write_text(updated, encoding="utf-8")

        new_count = count_tokens(updated)
        await self._update_index_token_count(filename, new_count)

    async def _update_index(self, meta: SnapshotMeta) -> None:
        index_path = self.snapshots_dir / "index.json"
        index = self._read_index(index_path)
        index["snapshots"].append(meta.__dict__)

        # Keep sorted newest-first
        index["snapshots"].sort(
            key=lambda s: f"{s['date']}-{s['time']}", reverse=True
        )
        index_path.write_text(json.dumps(index, indent=2), encoding="utf-8")

    async def _update_index_token_count(self, filename: str, count: int) -> None:
        index_path = self.snapshots_dir / "index.json"
        index = self._read_index(index_path)
        for s in index["snapshots"]:
            if s["file"] == filename:
                s["token_count"] = count
                break
        index_path.write_text(json.dumps(index, indent=2), encoding="utf-8")

    def _read_index(self, path: Path) -> dict:
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            return {"snapshots": []}

    @staticmethod
    def _slugify(text: str, max_len: int = 30) -> str:
        slug = re.sub(r"[^a-z0-9]", "-", text.lower())
        slug = re.sub(r"-+", "-", slug).strip("-")
        return slug[:max_len]