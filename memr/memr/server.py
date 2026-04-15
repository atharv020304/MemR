# """
# MemR MCP Server — Python implementation.

# Exposes vault management, snapshot read/write, and budget-aware loading
# as MCP tools over stdio transport.
# """

# from __future__ import annotations
# import json
# import logging
# from typing import Any

# from mcp.server import Server
# from mcp.server.stdio import stdio_server
# from mcp.types import Tool, TextContent

# from memr.types import SessionMode, Lens
# from memr.config import resolve_memory_root
# from memr.vault.manager import VaultManager
# from memr.vault.context import VaultContext
# from memr.tokens.counter import count_tokens
# from memr.trace.emitter import TraceEmitter, NullEmitter

# logger = logging.getLogger("memr")


# class MemRServer:
#     def __init__(self, memory_root: str | None = None, tracer: TraceEmitter | None = None):
#         self.memory_root = resolve_memory_root(memory_root)
#         self.vault_mgr = VaultManager(self.memory_root)
#         self.contexts: dict[str, VaultContext] = {}
#         self.session_mode: SessionMode | None = None
#         self.tracer = tracer or NullEmitter()

#         self.app = Server("memr")
#         self._register_tools()
#         self._register_prompts()

#     # ── Helpers ──────────────────────────────────────────────────────────────

#     def _get_context(self, vault_name: str) -> VaultContext:
#         if vault_name not in self.contexts:
#             self.contexts[vault_name] = VaultContext(self.memory_root, vault_name)
#         return self.contexts[vault_name]

#     def _assert_write(self):
#         if self.session_mode == SessionMode.LOAD:
#             raise PermissionError(
#                 "READ-ONLY: session is in LOAD mode. Start an EDIT session to write."
#             )

#     def _ok(self, **data) -> list[TextContent]:
#         return [TextContent(type="text", text=json.dumps({"ok": True, **data}, indent=2))]

#     def _err(self, msg: str) -> list[TextContent]:
#         return [TextContent(type="text", text=json.dumps({"ok": False, "error": msg}))]

#     # ── Tool Registration ────────────────────────────────────────────────────

#     def _register_tools(self):

#         @self.app.list_tools()
#         async def list_tools() -> list[Tool]:
#             return [
#                 Tool(
#                     name="memr_set_mode",
#                     description=(
#                         "Set session mode. CREATE = new vault, LOAD = read-only, EDIT = read+write. "
#                         "Must be called once at session start."
#                     ),
#                     inputSchema={
#                         "type": "object",
#                         "properties": {
#                             "mode": {"type": "string", "enum": ["create", "load", "edit"]},
#                             "vault": {"type": "string", "description": "Vault name (required for load/edit)"},
#                         },
#                         "required": ["mode"],
#                     },
#                 ),
#                 Tool(
#                     name="memr_create_vault",
#                     description="Create a new vault for a project, service, or feature.",
#                     inputSchema={
#                         "type": "object",
#                         "properties": {
#                             "name": {"type": "string"},
#                             "description": {"type": "string"},
#                         },
#                         "required": ["name"],
#                     },
#                 ),
#                 Tool(
#                     name="memr_list_vaults",
#                     description="List all available vaults.",
#                     inputSchema={"type": "object", "properties": {}},
#                 ),
#                 Tool(
#                     name="memr_delete_vault",
#                     description="Permanently delete a vault.",
#                     inputSchema={
#                         "type": "object",
#                         "properties": {"name": {"type": "string"}},
#                         "required": ["name"],
#                     },
#                 ),
#                 Tool(
#                     name="memr_save_snapshot",
#                     description=(
#                         "Save a session snapshot using Decision Notation. "
#                         "Call at session end or after major decisions.\n\n"
#                         "DECISION NOTATION:\n"
#                         "→  decided/shipped [over: alt | reason: why]\n"
#                         "↛  explored but abandoned [reason: why | replaced: what]\n"
#                         "⚡ surprise / non-obvious bug / trap\n"
#                         "◌  open thread — unresolved or deferred [context: why]\n"
#                         "Δ  code delta → path/to/file.py:line\n"
#                         "⊕  external constraint (legal, client, ops, team)\n"
#                         "?? question with non-obvious answer\n"
#                         ">> the answer / resolution\n\n"
#                         "RULES: Only save what CANNOT be recovered from reading code."
#                     ),
#                     inputSchema={
#                         "type": "object",
#                         "properties": {
#                             "vault": {"type": "string"},
#                             "topic": {"type": "string", "description": "Short topic summary"},
#                             "content": {"type": "string", "description": "DN-formatted snapshot content"},
#                         },
#                         "required": ["vault", "topic", "content"],
#                     },
#                 ),
#                 Tool(
#                     name="memr_load_snapshots",
#                     description=(
#                         "Load snapshots from a vault with optional filtering. "
#                         "Respects token budget — stops loading when budget is hit."
#                     ),
#                     inputSchema={
#                         "type": "object",
#                         "properties": {
#                             "vault": {"type": "string"},
#                             "filter": {
#                                 "type": "string",
#                                 "enum": [
#                                     "recent", "topic", "date",
#                                     "surprises", "open", "abandoned", "constraints",
#                                 ],
#                             },
#                             "value": {"type": "string", "description": "Filter argument"},
#                             "token_budget": {
#                                 "type": "integer",
#                                 "description": "Max tokens to load (default: 4000)",
#                             },
#                         },
#                         "required": ["vault", "filter"],
#                     },
#                 ),
#                 Tool(
#                     name="memr_list_snapshots",
#                     description="List snapshot metadata for a vault (no content loaded).",
#                     inputSchema={
#                         "type": "object",
#                         "properties": {"vault": {"type": "string"}},
#                         "required": ["vault"],
#                     },
#                 ),
#                 Tool(
#                     name="memr_compact",
#                     description=(
#                         "Merge or prune old snapshots in a vault. "
#                         "Deduplicates decisions, resolves closed questions, keeps all surprises."
#                     ),
#                     inputSchema={
#                         "type": "object",
#                         "properties": {
#                             "vault": {"type": "string"},
#                             "strategy": {
#                                 "type": "string",
#                                 "enum": ["merge_recent", "prune_resolved"],
#                             },
#                             "count": {
#                                 "type": "integer",
#                                 "description": "Number of snapshots to merge (for merge_recent)",
#                             },
#                         },
#                         "required": ["vault", "strategy"],
#                     },
#                 ),
#                 Tool(
#                     name="memr_vault_summary",
#                     description="Get a lightweight summary of a vault (~50-100 tokens).",
#                     inputSchema={
#                         "type": "object",
#                         "properties": {"vault": {"type": "string"}},
#                         "required": ["vault"],
#                     },
#                 ),
#             ]

#         @self.app.call_tool()
#         async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
#             try:
#                 return await self._dispatch(name, arguments)
#             except Exception as e:
#                 logger.exception(f"Tool error: {name}")
#                 return self._err(str(e))

#     # ── Tool Dispatch ────────────────────────────────────────────────────────

#     async def _dispatch(self, name: str, args: dict[str, Any]) -> list[TextContent]:

#         # ── Mode ─────────────────────────────────────────────────────────
#         if name == "memr_set_mode":
#             mode = SessionMode(args["mode"])
#             vault = args.get("vault")

#             if mode in (SessionMode.LOAD, SessionMode.EDIT) and not vault:
#                 raise ValueError(f"vault is required for {mode.value} mode")

#             if vault:
#                 v = await self.vault_mgr.get(vault)
#                 if not v:
#                     raise ValueError(f'Vault "{vault}" not found. Use memr_list_vaults.')
#                 self.vault_mgr.select([vault])

#             self.session_mode = mode

#             with self.tracer.span("set_mode", mode=mode.value, vault=vault):
#                 pass

#             next_step = (
#                 f'Call memr_create_vault({{name: "...", description: "..."}})'
#                 if mode == SessionMode.CREATE
#                 else f'Call memr_load_snapshots({{vault: "{vault}", filter: "recent", value: "3"}})'
#             )
#             return self._ok(mode=mode.value, vault=vault, next_step=next_step)

#         # ── Vault CRUD ───────────────────────────────────────────────────
#         if name == "memr_create_vault":
#             await self.vault_mgr.initialize()
#             vault = await self.vault_mgr.create(args["name"], args.get("description"))
#             return self._ok(message=f'Created vault "{vault.name}"', vault=vault.__dict__)

#         if name == "memr_list_vaults":
#             vaults = await self.vault_mgr.list_all()
#             return self._ok(
#                 vaults=[v.__dict__ for v in vaults],
#                 selected=self.vault_mgr.get_selected(),
#             )

#         if name == "memr_delete_vault":
#             self._assert_write()
#             await self.vault_mgr.delete(args["name"])
#             self.contexts.pop(args["name"], None)
#             return self._ok(message=f'Deleted vault "{args["name"]}"')

#         # ── Snapshots ────────────────────────────────────────────────────
#         if name == "memr_save_snapshot":
#             self._assert_write()
#             vault, topic, content = args["vault"], args["topic"], args["content"]

#             ctx = self._get_context(vault)
#             with self.tracer.span("save_snapshot", vault=vault, topic=topic):
#                 meta = await ctx.writer.save(topic, content)

#             return self._ok(message=f"Snapshot saved: {meta.file}", meta=meta.__dict__)

#         if name == "memr_load_snapshots":
#             vault = args["vault"]
#             filt = args["filter"]
#             value = args.get("value")
#             budget = args.get("token_budget", 4000)

#             ctx = self._get_context(vault)

#             with self.tracer.span("load_snapshots", vault=vault, filter=filt, budget=budget) as span:
#                 result = await ctx.loader.load(filt, value, max_tokens=budget)
#                 span.set_metadata(
#                     snapshots_loaded=len(result.snapshots),
#                     tokens_used=result.total_tokens,
#                 )

#             combined = "\n\n───────────────────────\n\n".join(
#                 s.content for s in result.snapshots
#             )
#             return self._ok(
#                 vault=vault,
#                 filter=filt,
#                 snapshots_loaded=len(result.snapshots),
#                 total_tokens=result.total_tokens,
#                 budget_remaining=budget - result.total_tokens,
#                 content=combined,
#             )

#         if name == "memr_list_snapshots":
#             ctx = self._get_context(args["vault"])
#             snapshots = await ctx.loader.list_all()
#             summary = await ctx.loader.get_summary()
#             return self._ok(vault=args["vault"], summary=summary, snapshots=[s.__dict__ for s in snapshots])

#         # ── Compact ──────────────────────────────────────────────────────
#         if name == "memr_compact":
#             self._assert_write()
#             ctx = self._get_context(args["vault"])
#             strategy = args["strategy"]
#             count = args.get("count", 5)

#             with self.tracer.span("compact", vault=args["vault"], strategy=strategy):
#                 result = await ctx.compactor.run(strategy, count)

#             return self._ok(**result)

#         # ── Summary ──────────────────────────────────────────────────────
#         if name == "memr_vault_summary":
#             ctx = self._get_context(args["vault"])
#             summary = await ctx.loader.get_summary()
#             return self._ok(vault=args["vault"], summary=summary)

#         raise ValueError(f"Unknown tool: {name}")

#     # ── Prompts ──────────────────────────────────────────────────────────────

#     def _register_prompts(self):
#         @self.app.list_prompts()
#         async def list_prompts():
#             return [
#                 {"name": "session-start", "description": "Initialize MemR session with vault selection"},
#                 {"name": "session-info", "description": "Show current session mode and selected vaults"},
#             ]

#     # ── Start ────────────────────────────────────────────────────────────────

#     async def start(self):
#         await self.vault_mgr.initialize()
#         logger.info(f"MemR server starting — root: {self.memory_root}")

#         async with stdio_server() as (read, write):
#             await self.app.run(read, write, self.app.create_initialization_options())\



"""
MemR MCP Server — Python implementation.

Exposes two modes of operation:
  AUTO MODE (recommended):
    memr_auto_context  → auto-loads on first call, skips on repeat
    memr_track         → records decisions/surprises during work
    memr_checkpoint    → auto-saves when enough content accumulated

  MANUAL MODE (power users):
    memr_set_mode / memr_create_vault / memr_load_snapshots / memr_save_snapshot
    (original tools, still available for explicit control)

Both modes share the same vault storage and snapshot format.
"""

from __future__ import annotations
import json
import logging
from typing import Any

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

from memr.types import SessionMode, Lens, LoadResult
from memr.config import resolve_memory_root
from memr.vault.manager import VaultManager
from memr.vault.context import VaultContext
from memr.vault.auto import AutoProvisioner
from memr.lifecycle import SessionMemory, SNAPSHOT_SECTION_JOIN
from memr.tokens.counter import count_tokens
from memr.trace.emitter import TraceEmitter, NullEmitter

logger = logging.getLogger("memr")

# Session token budget (snapshots loaded into context). Raised via memr_set_session_token_budget
# after user approval when responses report truncated_by_budget.
DEFAULT_SESSION_TOKEN_BUDGET = 3000
MIN_SESSION_TOKEN_BUDGET = 500
MAX_SESSION_TOKEN_BUDGET = 500_000


# First MemR tool in this MCP process (except explicit load / vault CRUD) warms the vault
# the same way memr_load_snapshots(recent, budget) would — no separate storage layer.
_MEMR_PREWARM_SKIP = frozenset(
    {
        "memr_list_vaults",
        "memr_create_vault",
        "memr_delete_vault",
        "memr_load_snapshots",
        "memr_set_session_token_budget",
    }
)

# Shipped on every MCP initialize — clients inject this for any agent using MemR (no repo rules required).
MEMR_MCP_INSTRUCTIONS = """\
You have access to MemR: persistent shared memory for this workspace (vaults + snapshots).

Workflow (default — follow unless the user opts out):
1. At the start of handling a new user request, call memr_auto_context first. Pass topic_hint with subsystem or file keywords from the user request (e.g. discovery, gateway) so matching snapshots are merged even after a warm load. Use force_refresh=true if you need a full reload. Skip only if you already pulled MemR in this same turn.
2. Prefer MemR when it already answers the question. When it does not (wrong topic, empty, thin, or missing the subsystem the user asked about), use grep / codebase search / file reads as needed to answer correctly or verify behavior.
3. Write-back rule (required): If you consulted the repository because MemR did not already hold that knowledge, persist reusable findings before you finish — use memr_track for each distinct fact (e.g. surprise for non-obvious behavior, qa with "question | short answer" for how code works, delta for important path:line anchors, decided when you chose between approaches), then memr_checkpoint(force=true). Goal: the next memr_auto_context includes what you learned; do not leave substantive discoveries only in the chat. Skip only when there is nothing another session would reuse.
4. If a MemR tool returns truncated_by_budget=true, more snapshots exist than fit the current token budget. Call memr_set_session_token_budget with a higher value (or pass a larger token_budget), then memr_auto_context(force_refresh=true) or memr_load_snapshots again if you need the rest.

memr_track and memr_checkpoint auto-load the vault on first use if memr_auto_context was not called."""


class MemRServer:
    def __init__(self, memory_root: str | None = None, tracer: TraceEmitter | None = None):
        self.memory_root = resolve_memory_root(memory_root)
        self.vault_mgr = VaultManager(self.memory_root)
        self.auto = AutoProvisioner(self.vault_mgr)
        self.session_memory = SessionMemory(self.vault_mgr, tracer=tracer)
        self.contexts: dict[str, VaultContext] = {}
        self.session_mode: SessionMode | None = None
        self.tracer = tracer or NullEmitter()
        self.session_token_budget = DEFAULT_SESSION_TOKEN_BUDGET

        self.app = Server("memr", instructions=MEMR_MCP_INSTRUCTIONS)
        self._register_tools()
        self._register_prompts()

    # ── Helpers ──────────────────────────────────────────────────────────────

    def _clamp_token_budget(self, n: int) -> int:
        return max(MIN_SESSION_TOKEN_BUDGET, min(MAX_SESSION_TOKEN_BUDGET, int(n)))

    @staticmethod
    def _budget_escalation_fields(result: LoadResult, token_budget_used: int) -> dict[str, Any]:
        if not result.truncated_by_budget:
            return {}
        floor = result.next_snapshot_min_tokens
        floor_txt = (
            f" Use at least token_budget={floor} to include the next blocked snapshot in full."
            if floor is not None
            else ""
        )
        return {
            "truncated_by_budget": True,
            "snapshots_omitted": result.snapshots_omitted,
            "next_snapshot_min_tokens": floor,
            "token_budget_used": token_budget_used,
            "agent_guidance": (
                "Memory load hit the token budget before every matching snapshot could be loaded. "
                "Call memr_set_session_token_budget with a higher session cap (or pass a larger "
                "token_budget on the next load), then memr_auto_context(force_refresh=true) or "
                "memr_load_snapshots again."
                + floor_txt
            ),
        }

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
                # ═══════════════════════════════════════════════════════
                # AUTO MODE TOOLS (recommended — zero manual steps)
                # ═══════════════════════════════════════════════════════
                Tool(
                    name="memr_auto_context",
                    description=(
                        "PRIMARY CONTEXT SOURCE — call this before repo search (grep, codebase_search, "
                        "list_dir) whenever the user sends a new request, unless you already loaded "
                        "memory this turn. Auto-creates a vault if missing, loads recent snapshots, "
                        "merges same-day updates. First load fills the token budget with newest snapshots "
                        "(not only three). topic_hint always runs: matching snapshots are added even when "
                        "already_loaded. force_refresh clears the session load cache and reloads. "
                        "If truncated_by_budget appears in a prior response, raise the limit via "
                        "memr_set_session_token_budget or pass token_budget here (optionally "
                        "as_session_default=true to remember for the rest of this MCP session)."
                    ),
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "vault": {
                                "type": "string",
                                "description": "Optional vault name. Auto-detected from project if omitted.",
                            },
                            "topic_hint": {
                                "type": "string",
                                "description": (
                                    "Keywords to match snapshot topics and filenames (e.g. discovery, eureka). "
                                    "Use the user's subsystem or feature name so relevant .snap files are included."
                                ),
                            },
                            "force_refresh": {
                                "type": "boolean",
                                "description": "If true, drop cached load state and reload recent snapshots from disk.",
                            },
                            "token_budget": {
                                "type": "integer",
                                "description": (
                                    "Max snapshot tokens for this call (warm load + topic_hint merge). "
                                    "Defaults to the session budget from memr_set_session_token_budget (initially 3000)."
                                ),
                            },
                            "as_session_default": {
                                "type": "boolean",
                                "description": (
                                    "If true and token_budget is set, also store that value as the session default "
                                    "for later tools and prewarm loads."
                                ),
                            },
                        },
                    },
                ),
                Tool(
                    name="memr_track",
                    description=(
                        "Record a notable event during the session. Call whenever you "
                        "decide, find a surprise, reject an approach, or change a file. "
                        "MemR auto-saves into shared memory when enough is buffered (no need to wait "
                        "for session end). Same-day snapshots are merged (deduped lines).\n\n"
                        "Signal types:\n"
                        "  decided   — chose an approach (include what was rejected and why)\n"
                        "  surprise  — found something non-obvious, a bug, or a trap\n"
                        "  abandoned — tried something that didn't work (include why)\n"
                        "  delta     — modified a file\n"
                        "  open      — left something unresolved for later\n"
                        "  constraint— discovered an external rule (legal, team, client)\n"
                        "  qa        — question with non-obvious answer (format: question | answer)"
                    ),
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "signal": {
                                "type": "string",
                                "enum": [
                                    "decided", "surprise", "abandoned",
                                    "delta", "open", "constraint", "qa",
                                ],
                            },
                            "content": {
                                "type": "string",
                                "description": "What happened. Be terse — one fact per call.",
                            },
                            "topic": {
                                "type": "string",
                                "description": "Optional topic tag for this event.",
                            },
                        },
                        "required": ["signal", "content"],
                    },
                ),
                Tool(
                    name="memr_checkpoint",
                    description=(
                        "Flush the session buffer to the vault (merges into today's snapshot when one "
                        "exists). Auto-runs after memr_track once there is any substantive line "
                        "(decision, surprise, delta, open thread, etc.); call with force=true when the user "
                        "says goodbye, thanks, done, or wrap up."
                    ),
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "force": {
                                "type": "boolean",
                                "description": "Save even if threshold not met. Use at session end.",
                            },
                        },
                    },
                ),
                Tool(
                    name="memr_set_session_token_budget",
                    description=(
                        "Raise or lower the maximum snapshot tokens loaded per MemR load for this MCP session "
                        "(after the user approves a larger context budget). Does not reload memory by itself — "
                        "call memr_auto_context(force_refresh=true) or memr_load_snapshots afterward."
                    ),
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "token_budget": {
                                "type": "integer",
                                "description": (
                                    "Target max tokens for snapshot loads (clamped for safety). "
                                    "Typical values: 8000–32000 for long-context models."
                                ),
                            },
                        },
                        "required": ["token_budget"],
                    },
                ),

                # ═══════════════════════════════════════════════════════
                # MANUAL MODE TOOLS (power users / backward compat)
                # ═══════════════════════════════════════════════════════
                Tool(
                    name="memr_set_mode",
                    description=(
                        "MANUAL MODE: Set session mode. CREATE = new vault, LOAD = read-only, "
                        "EDIT = read+write. Only needed if NOT using memr_auto_context."
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
                        "MANUAL MODE: Save a session snapshot using Decision Notation. "
                        "Only needed if NOT using memr_track + memr_checkpoint.\n\n"
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
                        "MANUAL MODE: Load snapshots from a vault with optional filtering. "
                        "Only needed if NOT using memr_auto_context. "
                        "Respects token budget — stops loading when budget is hit. "
                        "If the response includes truncated_by_budget, call memr_set_session_token_budget "
                        "or pass a larger token_budget and reload."
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
                                "description": (
                                    "Max tokens to load. Defaults to the session budget set by "
                                    "memr_set_session_token_budget (initially 3000)."
                                ),
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
        # Warm-read vault once per session (same loader as memr_load_snapshots); skipped when
        # the tool is an explicit load or vault CRUD list/create/delete.
        if name.startswith("memr_") and name not in _MEMR_PREWARM_SKIP:
            await self.session_memory.ensure_loaded(
                args.get("vault"),
                max_tokens=self.session_token_budget,
            )

        # ═════════════════════════════════════════════════════════════════
        # AUTO MODE HANDLERS
        # ═════════════════════════════════════════════════════════════════

        if name == "memr_auto_context":
            return await self._handle_auto_context(args)

        if name == "memr_track":
            return await self._handle_track(args)

        if name == "memr_checkpoint":
            return await self._handle_checkpoint(args)

        if name == "memr_set_session_token_budget":
            self.session_token_budget = self._clamp_token_budget(int(args["token_budget"]))
            return self._ok(
                session_token_budget=self.session_token_budget,
                message=(
                    f"Session memory token budget set to {self.session_token_budget}. "
                    "Call memr_auto_context(force_refresh=true) or memr_load_snapshots to reload with this limit."
                ),
            )

        # ═════════════════════════════════════════════════════════════════
        # MANUAL MODE HANDLERS
        # ═════════════════════════════════════════════════════════════════

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
            vault_name = args.get("vault")
            topic, content = args["topic"], args["content"]

            # Auto-provision: create vault if missing, pick default if not specified
            vault = await self.auto.ensure_vault(vault_name)

            # Auto-set mode if not set yet
            if self.session_mode is None:
                self.session_mode = SessionMode.EDIT
                self.vault_mgr.select([vault])

            ctx = self._get_context(vault)
            with self.tracer.span("save_snapshot", vault=vault, topic=topic):
                meta = await ctx.writer.save(topic, content)

            return self._ok(message=f"Snapshot saved: {meta.file}", meta=meta.__dict__)

        if name == "memr_load_snapshots":
            vault_name = args.get("vault")
            filt = args["filter"]
            value = args.get("value")
            budget = self._clamp_token_budget(
                int(args.get("token_budget", self.session_token_budget))
            )

            # Auto-provision: pick default vault if not specified
            vault = await self.auto.ensure_vault(vault_name)

            # Auto-set mode if not set yet
            if self.session_mode is None:
                self.session_mode = SessionMode.LOAD
                self.vault_mgr.select([vault])

            ctx = self._get_context(vault)

            with self.tracer.span("load_snapshots", vault=vault, filter=filt, budget=budget) as span:
                result = await ctx.loader.load(filt, value, max_tokens=budget)
                span.set_metadata(
                    snapshots_loaded=len(result.snapshots),
                    tokens_used=result.total_tokens,
                    truncated_by_budget=result.truncated_by_budget,
                )

            combined = "\n\n───────────────────────\n\n".join(
                s.content for s in result.snapshots
            )
            payload: dict[str, Any] = {
                "vault": vault,
                "filter": filt,
                "snapshots_loaded": len(result.snapshots),
                "total_tokens": result.total_tokens,
                "budget_remaining": budget - result.total_tokens,
                "content": combined,
            }
            payload.update(self._budget_escalation_fields(result, budget))
            return self._ok(**payload)

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

    # ═════════════════════════════════════════════════════════════════════
    # AUTO MODE HANDLER IMPLEMENTATIONS
    # ═════════════════════════════════════════════════════════════════════

    async def _handle_auto_context(self, args: dict[str, Any]) -> list[TextContent]:
        """
        Auto-loads memory: budget-based recent snapshots, optional topic merge every call,
        optional force_refresh to ignore session cache.
        """
        vault = args.get("vault")
        topic_hint = (args.get("topic_hint") or "").strip() or None

        raw_tb = args.get("token_budget")
        effective = self.session_token_budget
        if raw_tb is not None:
            effective = self._clamp_token_budget(int(raw_tb))
            if args.get("as_session_default"):
                self.session_token_budget = effective

        if args.get("force_refresh"):
            self.session_memory.invalidate_load_cache()

        result = await self.session_memory.ensure_loaded(vault_name=vault, max_tokens=effective)
        vault_id = (result or {}).get("vault") or self.session_memory._loaded_vault

        extra_snaps: list = []
        topic_section: str | None = None
        topic_res: LoadResult | None = None
        if topic_hint and vault_id:
            ctx = self.session_memory._get_context(vault_id)
            topic_res = await ctx.loader.load("topic", topic_hint, max_tokens=effective)
            extra_snaps = [
                s for s in topic_res.snapshots if s.meta.file not in self.session_memory._loaded_files
            ]
            if extra_snaps:
                for s in extra_snaps:
                    self.session_memory._loaded_files.add(s.meta.file)
                    self.session_memory._loaded_topics.add(s.meta.topic.lower())
                topic_section = (
                    SNAPSHOT_SECTION_JOIN
                    + "## MemR: snapshots matching topic_hint\n\n"
                    + SNAPSHOT_SECTION_JOIN.join(s.content for s in extra_snaps)
                )

        topic_merge_fields: dict[str, Any] = {}
        if topic_res is not None and topic_res.truncated_by_budget:
            topic_merge_fields = {
                f"topic_merge_{k}": v
                for k, v in self._budget_escalation_fields(topic_res, effective).items()
            }

        if result is None:
            if topic_section:
                merged = topic_section.strip()
                payload: dict[str, Any] = {
                    "already_loaded": True,
                    "topic_focused_load": True,
                    "vault": vault_id,
                    "loaded_topics": sorted(self.session_memory._loaded_topics),
                    "snapshot_files": sorted(self.session_memory._loaded_files),
                    "snapshots_loaded": len(extra_snaps),
                    "total_tokens": count_tokens(merged),
                    "content": merged,
                    "session_token_budget": self.session_token_budget,
                    "message": (
                        f"Warm vault had no budget match for {topic_hint!r} earlier; "
                        f"loaded {len(extra_snaps)} additional snapshot(s)."
                    ),
                }
                payload.update(topic_merge_fields)
                return self._ok(**payload)
            if topic_merge_fields:
                return self._ok(
                    already_loaded=True,
                    vault=vault_id,
                    loaded_topics=sorted(self.session_memory._loaded_topics),
                    snapshot_files=sorted(self.session_memory._loaded_files),
                    session_token_budget=self.session_token_budget,
                    message=(
                        "Memory already loaded; topic_hint search hit the token budget before "
                        "every matching snapshot could be scanned. Raise the limit with "
                        "memr_set_session_token_budget or pass token_budget, then force_refresh=true "
                        "or a new topic_hint."
                    ),
                    **topic_merge_fields,
                )
            return self._ok(
                already_loaded=True,
                vault=self.session_memory._loaded_vault,
                loaded_topics=sorted(self.session_memory._loaded_topics),
                snapshot_files=sorted(self.session_memory._loaded_files),
                session_token_budget=self.session_token_budget,
                message=(
                    "Memory already loaded for this vault. Pass topic_hint (keywords from filenames "
                    "or topics, e.g. discovery-service) to pull in snapshots that were outside the "
                    "first budget slice, or force_refresh=true to reload."
                ),
            )

        if topic_section:
            merged = result["content"] + topic_section
            result["content"] = merged
            result["snapshots_loaded"] = result["snapshots_loaded"] + len(extra_snaps)
            result["total_tokens"] = count_tokens(merged)
            result["snapshot_files"] = list(result.get("snapshot_files", [])) + [
                s.meta.file for s in extra_snaps
            ]
            result["topic_hints_merged"] = topic_hint
            result.update(topic_merge_fields)
        elif topic_hint:
            result["topic_hint_note"] = (
                f"No extra snapshots matched topic_hint {topic_hint!r} "
                "(already included or no topic/filename match)."
            )
            result.update(topic_merge_fields)

        if self.session_mode is None:
            self.session_mode = SessionMode.EDIT
            self.vault_mgr.select([result["vault"]])

        if isinstance(result, dict):
            result = {**result, "session_token_budget": self.session_token_budget}
        return self._ok(**result)

    async def _handle_track(self, args: dict[str, Any]) -> list[TextContent]:
        """
        Records a single knowledge event into the session buffer.
        Ensures vault memory is loaded on first use; auto-saves when the buffer is worth persisting.
        """
        await self.session_memory.ensure_loaded()

        signal = args["signal"]
        content = args["content"]
        topic = args.get("topic")

        match signal:
            case "decided":
                self.session_memory.track_decision(content, topic)
            case "surprise":
                self.session_memory.track_surprise(content)
            case "abandoned":
                self.session_memory.track_abandoned(content)
            case "delta":
                self.session_memory.track_delta(content)
            case "open":
                self.session_memory.track_open(content)
            case "constraint":
                self.session_memory.track_constraint(content)
            case "qa":
                parts = content.split("|", 1)
                if len(parts) == 2:
                    self.session_memory.track_qa(parts[0].strip(), parts[1].strip())
                else:
                    self.session_memory.track_decision(content, topic)
            case _:
                self.session_memory.track_decision(content, topic)

        status = self.session_memory.get_status()
        buffer_size = sum(status["buffer_items"].values())

        meta = None
        if self.session_memory._buffer.is_worth_saving:
            meta = await self.session_memory.maybe_save()

        if meta:
            return self._ok(
                tracked=True,
                auto_saved=True,
                snapshot=meta.file,
                token_count=meta.token_count,
                buffer_size=0,
                message=f"Auto-saved to {meta.file} (merged into today's vault snapshot when applicable).",
            )

        return self._ok(
            tracked=True,
            signal=signal,
            buffer_size=buffer_size,
            worth_saving=status["worth_saving"],
        )

    async def _handle_checkpoint(self, args: dict[str, Any]) -> list[TextContent]:
        """
        Saves the session buffer as a snapshot.
        Called explicitly by the agent at session end, or when
        the user says goodbye/thanks/done.
        """
        await self.session_memory.ensure_loaded()
        force = args.get("force", False)
        meta = await self.session_memory.maybe_save(force=force)

        if meta is None:
            buf = self.session_memory._buffer
            if not buf.is_dirty:
                msg = (
                    "Nothing to save — the in-memory buffer is empty. "
                    "If memr_track already returned auto_saved=true, that data was written "
                    "(merged into today's snapshot); there is nothing extra for checkpoint to flush."
                )
            elif not force:
                msg = (
                    "Nothing to save — buffer is below the auto-save threshold. "
                    "Call memr_checkpoint with force=true to persist what is buffered anyway."
                )
            else:
                msg = "Nothing to save — buffer is empty."
            return self._ok(saved=False, message=msg)

        return self._ok(
            saved=True,
            file=meta.file,
            token_count=meta.token_count,
            topic=meta.topic,
            message=f"Checkpoint saved: {meta.file} ({meta.token_count} tokens).",
        )

    # ── Prompts ──────────────────────────────────────────────────────────────

    def _register_prompts(self):
        @self.app.list_prompts()
        async def list_prompts():
            return [
                {
                    "name": "session-start",
                    "description": "Initialize MemR session (use memr_auto_context instead for auto mode)",
                },
                {
                    "name": "session-info",
                    "description": "Show current session status, loaded vault, and buffer contents",
                },
            ]

    # ── Start ────────────────────────────────────────────────────────────────

    async def start(self):
        await self.vault_mgr.initialize()
        logger.info(f"MemR server starting — root: {self.memory_root}")

        async with stdio_server() as (read, write):
            await self.app.run(read, write, self.app.create_initialization_options())