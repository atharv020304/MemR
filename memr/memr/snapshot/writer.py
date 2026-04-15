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


def _flags_from_body(body: str) -> dict[str, bool]:
    return {
        "has_abandoned": Signal.ABANDONED.value in body,
        "has_surprises": Signal.SURPRISE.value in body,
        "has_open": Signal.OPEN.value in body,
        "has_context": Signal.CONTEXT.value in body,
    }


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

        flags = _flags_from_body(content)
        meta = SnapshotMeta(
            file=filename,
            date=date_str,
            time=time_str,
            vault=self.vault_name,
            topic=topic,
            token_count=token_count,
            **flags,
        )

        full_with_tokens = full_content.replace(
            "---\n", f"@tokens: {token_count}\n---\n"
        )
        filepath.write_text(full_with_tokens, encoding="utf-8")

        await self._update_index(meta)
        return meta

    @staticmethod
    def _split_header_body(full_text: str) -> tuple[str, str]:
        parts = full_text.split("---\n", 1)
        if len(parts) == 2:
            return parts[0] + "---\n", parts[1].strip()
        return "", full_text.strip()

    @staticmethod
    def _merge_bodies(old_body: str, new_body: str) -> str:
        old_lines = [ln for ln in old_body.splitlines() if ln.strip()]
        new_lines = [ln for ln in new_body.splitlines() if ln.strip()]
        seen = {ln.strip() for ln in old_lines}
        merged: list[str] = list(old_lines)
        for ln in new_lines:
            key = ln.strip()
            if key and key not in seen:
                merged.append(ln)
                seen.add(key)
        return "\n".join(merged) + ("\n" if merged else "")

    async def save_merged(self, topic: str, content: str) -> SnapshotMeta:
        """
        If this vault already has a snapshot from today, merge new DN lines
        into the newest same-day file (deduped by line). Otherwise save().
        """
        self.snapshots_dir.mkdir(parents=True, exist_ok=True)
        now = datetime.now()
        date_str = now.strftime("%Y-%m-%d")
        index_path = self.snapshots_dir / "index.json"
        index = self._read_index(index_path)
        today_snaps = [s for s in index.get("snapshots", []) if s.get("date") == date_str]
        if not today_snaps:
            return await self.save(topic, content)

        latest = max(today_snaps, key=lambda s: (s.get("time") or "", s.get("file") or ""))
        filename = latest["file"]
        filepath = self.snapshots_dir / filename
        if not filepath.is_file():
            return await self.save(topic, content)

        raw = filepath.read_text(encoding="utf-8")
        _, old_body = self._split_header_body(raw)
        merged_body = self._merge_bodies(old_body, content.strip())

        prev_topic = (latest.get("topic") or "").strip()
        t = topic.strip()
        if prev_topic and t and t not in prev_topic:
            combined_topic = f"{prev_topic} · {t}"[:500]
        else:
            combined_topic = prev_topic or t or "session"

        header = (
            f"@vault: {self.vault_name}\n"
            f"@when: {now.isoformat(timespec='minutes')}\n"
            f"@topic: {combined_topic}\n"
            "---\n"
        )
        full_content = header + merged_body.strip() + "\n"
        token_count = count_tokens(full_content)
        full_with_tokens = full_content.replace(
            "---\n", f"@tokens: {token_count}\n---\n", 1
        )
        filepath.write_text(full_with_tokens, encoding="utf-8")

        flags = _flags_from_body(merged_body)
        meta = SnapshotMeta(
            file=filename,
            date=str(latest.get("date", date_str)),
            time=str(latest.get("time", "")),
            vault=self.vault_name,
            topic=combined_topic,
            token_count=token_count,
            **flags,
        )
        await self._replace_index_entry(meta)
        return meta

    async def _replace_index_entry(self, meta: SnapshotMeta) -> None:
        index_path = self.snapshots_dir / "index.json"
        index = self._read_index(index_path)
        snaps = index.get("snapshots", [])
        new_list = [s for s in snaps if s.get("file") != meta.file]
        new_list.append(meta.__dict__)
        new_list.sort(key=lambda s: f"{s['date']}-{s['time']}", reverse=True)
        index["snapshots"] = new_list
        index_path.write_text(json.dumps(index, indent=2), encoding="utf-8")

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