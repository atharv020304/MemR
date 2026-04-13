"""
MemR MCP Server — Python implementation.

Exposes vault management, snapshot read/write, and budget-aware loading
as MCP tools over stdio transport.
"""

from __future__ import annotations
import json
import logging
from typing import Any

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

from memr.types import SessionMode, Lens
from memr.config import resolve_memory_root
from memr.vault.manager import VaultManager
from memr.vault.context import VaultContext
from memr.tokens.counter import count_tokens
from memr.trace.emitter import TraceEmitter, NullEmitter

logger = logging.getLogger("memr")


class MemRServer:
    def __init__(self, memory_root: str | None = None, tracer: TraceEmitter | None = None):
        self.memory_root = resolve_memory_root(memory_root)
        self.vault_mgr = VaultManager(self.memory_root)
        self.contexts: dict[str, VaultContext] = {}
        self.session_mode: SessionMode | None = None
        self.tracer = tracer or NullEmitter()

        self.app = Server("memr")
        self._register_tools()
        self._register_prompts()

    # ── Helpers ──────────────────────────────────────────────────────────────

    def _get_context(self, vault_name: str) -> VaultContext:
        if vault_name not in self.contexts:
            self.contexts[vault_name] = VaultContext(self.memory_root, vault_name)
        return self.contexts[vault_name]

    def _assert_write(self):
        if self.session_mode == SessionMode.LOAD:
            raise PermissionError(
                "READ-ONLY: session is in LOAD mode. Start an EDIT session to write."
            )

    def _ok(self, **data) -> list[TextContent]:
        return [TextContent(type="text", text=json.dumps({"ok": True, **data}, indent=2))]

    def _err(self, msg: str) -> list[TextContent]:
        return [TextContent(type="text", text=json.dumps({"ok": False, "error": msg}))]

    # ── Tool Registration ────────────────────────────────────────────────────

    def _register_tools(self):

        @self.app.list_tools()
        async def list_tools() -> list[Tool]:
            return [
                Tool(
                    name="memr_set_mode",
                    description=(
                        "Set session mode. CREATE = new vault, LOAD = read-only, EDIT = read+write. "
                        "Must be called once at session start."
                    ),
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "mode": {"type": "string", "enum": ["create", "load", "edit"]},
                            "vault": {"type": "string", "description": "Vault name (required for load/edit)"},
                        },
                        "required": ["mode"],
                    },
                ),
                Tool(
                    name="memr_create_vault",
                    description="Create a new vault for a project, service, or feature.",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "name": {"type": "string"},
                            "description": {"type": "string"},
                        },
                        "required": ["name"],
                    },
                ),
                Tool(
                    name="memr_list_vaults",
                    description="List all available vaults.",
                    inputSchema={"type": "object", "properties": {}},
                ),
                Tool(
                    name="memr_delete_vault",
                    description="Permanently delete a vault.",
                    inputSchema={
                        "type": "object",
                        "properties": {"name": {"type": "string"}},
                        "required": ["name"],
                    },
                ),
                Tool(
                    name="memr_save_snapshot",
                    description=(
                        "Save a session snapshot using Decision Notation. "
                        "Call at session end or after major decisions.\n\n"
                        "DECISION NOTATION:\n"
                        "→  decided/shipped [over: alt | reason: why]\n"
                        "↛  explored but abandoned [reason: why | replaced: what]\n"
                        "⚡ surprise / non-obvious bug / trap\n"
                        "◌  open thread — unresolved or deferred [context: why]\n"
                        "Δ  code delta → path/to/file.py:line\n"
                        "⊕  external constraint (legal, client, ops, team)\n"
                        "?? question with non-obvious answer\n"
                        ">> the answer / resolution\n\n"
                        "RULES: Only save what CANNOT be recovered from reading code."
                    ),
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "vault": {"type": "string"},
                            "topic": {"type": "string", "description": "Short topic summary"},
                            "content": {"type": "string", "description": "DN-formatted snapshot content"},
                        },
                        "required": ["vault", "topic", "content"],
                    },
                ),
                Tool(
                    name="memr_load_snapshots",
                    description=(
                        "Load snapshots from a vault with optional filtering. "
                        "Respects token budget — stops loading when budget is hit."
                    ),
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "vault": {"type": "string"},
                            "filter": {
                                "type": "string",
                                "enum": [
                                    "recent", "topic", "date",
                                    "surprises", "open", "abandoned", "constraints",
                                ],
                            },
                            "value": {"type": "string", "description": "Filter argument"},
                            "token_budget": {
                                "type": "integer",
                                "description": "Max tokens to load (default: 4000)",
                            },
                        },
                        "required": ["vault", "filter"],
                    },
                ),
                Tool(
                    name="memr_list_snapshots",
                    description="List snapshot metadata for a vault (no content loaded).",
                    inputSchema={
                        "type": "object",
                        "properties": {"vault": {"type": "string"}},
                        "required": ["vault"],
                    },
                ),
                Tool(
                    name="memr_compact",
                    description=(
                        "Merge or prune old snapshots in a vault. "
                        "Deduplicates decisions, resolves closed questions, keeps all surprises."
                    ),
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "vault": {"type": "string"},
                            "strategy": {
                                "type": "string",
                                "enum": ["merge_recent", "prune_resolved"],
                            },
                            "count": {
                                "type": "integer",
                                "description": "Number of snapshots to merge (for merge_recent)",
                            },
                        },
                        "required": ["vault", "strategy"],
                    },
                ),
                Tool(
                    name="memr_vault_summary",
                    description="Get a lightweight summary of a vault (~50-100 tokens).",
                    inputSchema={
                        "type": "object",
                        "properties": {"vault": {"type": "string"}},
                        "required": ["vault"],
                    },
                ),
            ]

        @self.app.call_tool()
        async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
            try:
                return await self._dispatch(name, arguments)
            except Exception as e:
                logger.exception(f"Tool error: {name}")
                return self._err(str(e))

    # ── Tool Dispatch ────────────────────────────────────────────────────────

    async def _dispatch(self, name: str, args: dict[str, Any]) -> list[TextContent]:

        # ── Mode ─────────────────────────────────────────────────────────
        if name == "memr_set_mode":
            mode = SessionMode(args["mode"])
            vault = args.get("vault")

            if mode in (SessionMode.LOAD, SessionMode.EDIT) and not vault:
                raise ValueError(f"vault is required for {mode.value} mode")

            if vault:
                v = await self.vault_mgr.get(vault)
                if not v:
                    raise ValueError(f'Vault "{vault}" not found. Use memr_list_vaults.')
                self.vault_mgr.select([vault])

            self.session_mode = mode

            with self.tracer.span("set_mode", mode=mode.value, vault=vault):
                pass

            next_step = (
                f'Call memr_create_vault({{name: "...", description: "..."}})'
                if mode == SessionMode.CREATE
                else f'Call memr_load_snapshots({{vault: "{vault}", filter: "recent", value: "3"}})'
            )
            return self._ok(mode=mode.value, vault=vault, next_step=next_step)

        # ── Vault CRUD ───────────────────────────────────────────────────
        if name == "memr_create_vault":
            await self.vault_mgr.initialize()
            vault = await self.vault_mgr.create(args["name"], args.get("description"))
            return self._ok(message=f'Created vault "{vault.name}"', vault=vault.__dict__)

        if name == "memr_list_vaults":
            vaults = await self.vault_mgr.list_all()
            return self._ok(
                vaults=[v.__dict__ for v in vaults],
                selected=self.vault_mgr.get_selected(),
            )

        if name == "memr_delete_vault":
            self._assert_write()
            await self.vault_mgr.delete(args["name"])
            self.contexts.pop(args["name"], None)
            return self._ok(message=f'Deleted vault "{args["name"]}"')

        # ── Snapshots ────────────────────────────────────────────────────
        if name == "memr_save_snapshot":
            self._assert_write()
            vault, topic, content = args["vault"], args["topic"], args["content"]

            ctx = self._get_context(vault)
            with self.tracer.span("save_snapshot", vault=vault, topic=topic):
                meta = await ctx.writer.save(topic, content)

            return self._ok(message=f"Snapshot saved: {meta.file}", meta=meta.__dict__)

        if name == "memr_load_snapshots":
            vault = args["vault"]
            filt = args["filter"]
            value = args.get("value")
            budget = args.get("token_budget", 4000)

            ctx = self._get_context(vault)

            with self.tracer.span("load_snapshots", vault=vault, filter=filt, budget=budget) as span:
                result = await ctx.loader.load(filt, value, max_tokens=budget)
                span.set_metadata(
                    snapshots_loaded=len(result.snapshots),
                    tokens_used=result.total_tokens,
                )

            combined = "\n\n───────────────────────\n\n".join(
                s.content for s in result.snapshots
            )
            return self._ok(
                vault=vault,
                filter=filt,
                snapshots_loaded=len(result.snapshots),
                total_tokens=result.total_tokens,
                budget_remaining=budget - result.total_tokens,
                content=combined,
            )

        if name == "memr_list_snapshots":
            ctx = self._get_context(args["vault"])
            snapshots = await ctx.loader.list_all()
            summary = await ctx.loader.get_summary()
            return self._ok(vault=args["vault"], summary=summary, snapshots=[s.__dict__ for s in snapshots])

        # ── Compact ──────────────────────────────────────────────────────
        if name == "memr_compact":
            self._assert_write()
            ctx = self._get_context(args["vault"])
            strategy = args["strategy"]
            count = args.get("count", 5)

            with self.tracer.span("compact", vault=args["vault"], strategy=strategy):
                result = await ctx.compactor.run(strategy, count)

            return self._ok(**result)

        # ── Summary ──────────────────────────────────────────────────────
        if name == "memr_vault_summary":
            ctx = self._get_context(args["vault"])
            summary = await ctx.loader.get_summary()
            return self._ok(vault=args["vault"], summary=summary)

        raise ValueError(f"Unknown tool: {name}")

    # ── Prompts ──────────────────────────────────────────────────────────────

    def _register_prompts(self):
        @self.app.list_prompts()
        async def list_prompts():
            return [
                {"name": "session-start", "description": "Initialize MemR session with vault selection"},
                {"name": "session-info", "description": "Show current session mode and selected vaults"},
            ]

    # ── Start ────────────────────────────────────────────────────────────────

    async def start(self):
        await self.vault_mgr.initialize()
        logger.info(f"MemR server starting — root: {self.memory_root}")

        async with stdio_server() as (read, write):
            await self.app.run(read, write, self.app.create_initialization_options())