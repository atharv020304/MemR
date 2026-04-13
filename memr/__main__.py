import asyncio
import sys
import os
import logging

from memr.server import MemRServer
from memr.trace.emitter import NullEmitter

logging.basicConfig(
    level=logging.DEBUG if os.getenv("MEMR_DEBUG") else logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    stream=sys.stderr,
)


def resolve_tracer():
    """Pick trace backend based on available env vars."""
    if os.getenv("LANGCHAIN_API_KEY"):
        from memr.trace.langsmith import LangSmithEmitter
        return LangSmithEmitter(project=os.getenv("LANGCHAIN_PROJECT", "memr"))

    if os.getenv("LANGWATCH_API_KEY"):
        from memr.trace.langwatch import LangwatchEmitter
        return LangwatchEmitter()

    return NullEmitter()


async def main():
    memory_root = sys.argv[1] if len(sys.argv) > 1 else os.getenv("MEMR_PATH")
    tracer = resolve_tracer()
    server = MemRServer(memory_root=memory_root, tracer=tracer)
    await server.start()


def entry():
    """Console script entry point (used by pyproject.toml [project.scripts])."""
    asyncio.run(main())


if __name__ == "__main__":
    entry()


