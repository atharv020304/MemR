from __future__ import annotations
import logging
from contextlib import contextmanager
from typing import Any, Generator

from memr.trace.emitter import TraceEmitter, Span

logger = logging.getLogger("memr.trace.langsmith")


class LangSmithEmitter(TraceEmitter):

    def __init__(self, project: str = "memr"):
        self.project = project
        self._client = None
        self._available = False

        try:
            from langsmith import Client
            self._client = Client()
            self._available = True
            logger.info(f"LangSmith tracing enabled (project: {project})")
        except ImportError:
            logger.warning(
                "langsmith package not installed. "
                "Install with: pip install memr[langsmith]"
            )
        except Exception as e:
            logger.warning(f"LangSmith init failed: {e}")

    @contextmanager
    def span(self, name: str, **kw: Any) -> Generator[Span, None, None]:
        s = Span(name=name, metadata=kw)
        try:
            yield s
        finally:
            s.close()
            self._send(s)
            logger.debug(f"[langsmith] {s.name} ({s.duration_ms:.1f}ms) {s.metadata}")

    def _send(self, s: Span) -> None:
        if not self._available:
            return
        try:
            from langsmith.run_trees import RunTree

            run = RunTree(
                name=s.name,
                run_type="tool",
                project_name=self.project,
                inputs={"metadata": s.metadata},
            )
            run.end(outputs={
                "duration_ms": s.duration_ms,
                **s.metadata,
            })
            run.post()
        except Exception as e:
            logger.warning(f"Failed to send trace to LangSmith: {e}")

    def flush(self) -> None:
        pass

