"""
MemR Trace Emitter — abstract interface + null implementation.

Concrete adapters live in langsmith.py and langwatch.py.
Every tool call and relay decision emits a trace span for
real-time monitoring of token flow and routing decisions.
"""

from __future__ import annotations
import time
import logging
from abc import ABC, abstractmethod
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, Generator

logger = logging.getLogger("memr.trace")


@dataclass
class Span:
    """A single trace span with timing and metadata."""
    name: str
    start_time: float = field(default_factory=time.time)
    end_time: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def set_metadata(self, **kw: Any) -> None:
        self.metadata.update(kw)

    def close(self) -> None:
        self.end_time = time.time()

    @property
    def duration_ms(self) -> float:
        if self.end_time is None:
            return 0
        return (self.end_time - self.start_time) * 1000


class TraceEmitter(ABC):
    """Abstract base — implement span() and flush() for each backend."""

    @abstractmethod
    @contextmanager
    def span(self, name: str, **initial_meta: Any) -> Generator[Span, None, None]:
        ...

    @abstractmethod
    def flush(self) -> None:
        ...


class NullEmitter(TraceEmitter):
    """No-op emitter used when tracing is disabled."""

    @contextmanager
    def span(self, name: str, **kw: Any) -> Generator[Span, None, None]:
        yield Span(name=name, metadata=kw)

    def flush(self) -> None:
        pass