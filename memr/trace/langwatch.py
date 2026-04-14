from __future__ import annotations
import logging
from contextlib import contextmanager
from typing import Any, Generator

from memr.trace.emitter import TraceEmitter, Span

logger = logging.getLogger("memr.trace.langwatch")


class LangwatchEmitter(TraceEmitter):

    def __init__(self):
        self._lw = None
        self._available = False

        try:
            import langwatch
            self._lw = langwatch
            self._available = True
            logger.info("Langwatch tracing enabled")
        except ImportError:
            logger.warning(
                "langwatch package not installed. "
                "Install with: pip install memr[langwatch]"
            )
        except Exception as e:
            logger.warning(f"Langwatch init failed: {e}")

    @contextmanager
    def span(self, name: str, **kw: Any) -> Generator[Span, None, None]:
        s = Span(name=name, metadata=kw)

        # Use langwatch's native trace context if available
        lw_span = None
        if self._available:
            try:
                lw_span = self._lw.trace(name=name, metadata=kw)
                if hasattr(lw_span, "__enter__"):
                    lw_span.__enter__()
            except Exception:
                lw_span = None

        try:
            yield s
        finally:
            s.close()

            if lw_span and hasattr(lw_span, "__exit__"):
                try:
                    lw_span.__exit__(None, None, None)
                except Exception:
                    pass

            self._send(s)
            logger.debug(f"[langwatch] {s.name} ({s.duration_ms:.1f}ms) {s.metadata}")

    def _send(self, s: Span) -> None:
        if not self._available:
            return
        try:
            self._lw.capture_rag(
                name=s.name,
                input=str(s.metadata),
                output=f"completed in {s.duration_ms:.1f}ms",
                metadata={
                    "duration_ms": s.duration_ms,
                    **s.metadata,
                },
            )
        except Exception as e:
            logger.warning(f"Failed to send trace to Langwatch: {e}")

    def flush(self) -> None:
        if self._available:
            try:
                self._lw.flush()
            except Exception as e:
                logger.warning(f"Langwatch flush failed: {e}")
