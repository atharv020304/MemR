"""
MemR Signal Parser — extracts structured data from Decision Notation content.

Parses .snap body content into typed lines, each tagged with its signal type.
Used by the compactor for dedup/prune logic and by the loader for filtering.
"""

from __future__ import annotations
import re
from dataclasses import dataclass
from typing import Optional

from memr.types import Signal, SIGNAL_PATTERNS


@dataclass
class ParsedLine:
    """A single line from a snapshot, parsed into signal + body."""
    raw: str                         # original line as-is
    signal: Optional[Signal]         # None if line has no signal marker
    body: str                        # text after the signal marker
    annotation: Optional[str] = None # bracketed annotation [over: X | reason: Y]


class SignalParser:
    """Parse Decision Notation content into structured lines."""

    def __init__(self):
        # Compile regex patterns once
        self._patterns: list[tuple[Signal, re.Pattern]] = [
            (sig, re.compile(pat)) for sig, pat in SIGNAL_PATTERNS.items()
        ]
        # Matches bracketed annotations like [over: X | reason: Y]
        self._annotation_re = re.compile(r"\[([^\]]+)\]")

    def parse(self, content: str) -> list[ParsedLine]:
        """Parse a block of DN content into ParsedLine objects."""
        lines: list[ParsedLine] = []
        for raw_line in content.splitlines():
            stripped = raw_line.strip()
            if not stripped:
                continue
            lines.append(self._parse_line(stripped))
        return lines

    def _parse_line(self, line: str) -> ParsedLine:
        """Parse a single line into signal, body, and annotation."""
        for signal, pattern in self._patterns:
            match = pattern.match(line)
            if match:
                body = line[match.end():].strip()
                annotation = self._extract_annotation(body)
                return ParsedLine(
                    raw=line,
                    signal=signal,
                    body=body,
                    annotation=annotation,
                )

        # No signal marker — plain text line (context, continuation, etc.)
        return ParsedLine(raw=line, signal=None, body=line)

    def _extract_annotation(self, text: str) -> Optional[str]:
        """Extract [bracketed annotation] from a line body."""
        match = self._annotation_re.search(text)
        return match.group(1) if match else None

    # ── Filtering Helpers ────────────────────────────────────────────────

    def filter_by_signal(
        self, lines: list[ParsedLine], *signals: Signal
    ) -> list[ParsedLine]:
        """Return only lines matching the given signal types."""
        sig_set = set(signals)
        return [l for l in lines if l.signal in sig_set]

    def extract_surprises(self, content: str) -> list[str]:
        """Quick extraction of all ⚡ lines from raw content."""
        lines = self.parse(content)
        return [l.body for l in lines if l.signal == Signal.SURPRISE]

    def extract_open_threads(self, content: str) -> list[str]:
        """Quick extraction of all ◌ lines from raw content."""
        lines = self.parse(content)
        return [l.body for l in lines if l.signal == Signal.OPEN]

    def extract_decisions(self, content: str) -> list[str]:
        """Quick extraction of all → lines from raw content."""
        lines = self.parse(content)
        return [l.body for l in lines if l.signal == Signal.DECIDED]

    def has_signal(self, content: str, signal: Signal) -> bool:
        """Check if content contains at least one line with the given signal."""
        pattern = SIGNAL_PATTERNS[signal]
        return bool(re.search(pattern, content, re.MULTILINE))