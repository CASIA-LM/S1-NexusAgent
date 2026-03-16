"""NexusAgent CLI agent factory.

Replaces create_cli_agent() with an implementation that uses the S1-NexusAgent graph
as the primary agent, while keeping all Deep Agents CLI infrastructure
(backends, middleware, Textual UI).

Note: S1-NexusAgent is the project name, not a version number.
"""

from __future__ import annotations

import logging
import os
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING, Any

from deepagents.backends import CompositeBackend, LocalShellBackend
from deepagents.backends.filesystem import FilesystemBackend
from deepagents.middleware import MemoryMiddleware, SkillsMiddleware
from langgraph.checkpoint.memory import InMemorySaver

if TYPE_CHECKING:
    from deepagents.backends.sandbox import SandboxBackendProtocol
    from langgraph.checkpoint.base import BaseCheckpointSaver
    from langgraph.pregel import Pregel

    from deepagents_cli.mcp_tools import MCPServerInfo

from deepagents_cli.config import settings
from deepagents_cli.local_context import LocalContextMiddleware, _ExecutableBackend

logger = logging.getLogger(__name__)


async def create_nexus_cli_agent(
    assistant_id: str = "nexus",
    *,
    sandbox: SandboxBackendProtocol | None = None,
    sandbox_type: str | None = None,
    auto_approve: bool = False,
    enable_memory: bool = True,
    enable_skills: bool = True,
    enable_shell: bool = True,
    checkpointer: BaseCheckpointSaver | None = None,
    mcp_server_info: list[MCPServerInfo] | None = None,
) -> tuple[Pregel, CompositeBackend]:
    """Create a CLI agent powered by the S1-NexusAgent graph.

    Mirrors the interface of deepagents_cli.agent.create_cli_agent() so it
    can be used as a drop-in replacement, but builds the NexusAgent graph
    instead of the default Deep Agents agent graph.

    Args:
        assistant_id: Agent identifier for memory/state storage.
        sandbox: Optional sandbox backend for remote execution.
        sandbox_type: Type of sandbox provider.
        auto_approve: If True, skip HITL prompts.
        enable_memory: Enable MemoryMiddleware for persistent memory.
        enable_skills: Enable SkillsMiddleware for SKILL.md loading.
        enable_shell: Enable shell execution via LocalShellBackend.
        checkpointer: Checkpointer for session persistence.
        mcp_server_info: MCP server metadata for system prompt.

    Returns:
        2-tuple of (compiled_graph, composite_backend).
    """
    # ── 1. Setup agent directory ──
    if enable_memory or enable_skills:
        agent_dir = settings.ensure_agent_dir(assistant_id)
        agent_md = agent_dir / "AGENTS.md"
        if not agent_md.exists():
            agent_md.write_text(
                "# S1-NexusAgent\n\n"
                "AI4Science research assistant for biology, chemistry, "
                "and materials science.\n"
            )

    # ── 2. Build middleware stack ──
    agent_middleware = []

    if enable_memory:
        memory_sources = [str(settings.get_user_agent_md_path(assistant_id))]
        memory_sources.extend(str(p) for p in settings.get_project_agent_md_path())
        agent_middleware.append(
            MemoryMiddleware(
                backend=FilesystemBackend(),
                sources=memory_sources,
            )
        )

    if enable_skills:
        skills_dir = settings.ensure_user_skills_dir(assistant_id)
        user_agent_skills_dir = settings.get_user_agent_skills_dir()
        project_skills_dir = settings.get_project_skills_dir()
        project_agent_skills_dir = settings.get_project_agent_skills_dir()

        sources = [str(settings.get_built_in_skills_dir())]
        sources.extend([str(skills_dir), str(user_agent_skills_dir)])
        if project_skills_dir:
            sources.append(str(project_skills_dir))
        if project_agent_skills_dir:
            sources.append(str(project_agent_skills_dir))

        # Also include our own skills directory
        own_skills = Path(__file__).resolve().parent.parent / "skills"
        if own_skills.is_dir():
            sources.append(str(own_skills))

        agent_middleware.append(
            SkillsMiddleware(
                backend=FilesystemBackend(),
                sources=sources,
            )
        )

    # ── 3. Setup backend ──
    if sandbox is None:
        if enable_shell:
            shell_env = os.environ.copy()
            if settings.user_langchain_project:
                shell_env["LANGSMITH_PROJECT"] = settings.user_langchain_project
            backend = LocalShellBackend(
                root_dir=Path.cwd(),
                inherit_env=True,
                env=shell_env,
            )
        else:
            backend = FilesystemBackend()
    else:
        backend = sandbox

    # LocalContext middleware (git info, directory tree)
    if isinstance(backend, _ExecutableBackend):
        agent_middleware.append(
            LocalContextMiddleware(backend=backend, mcp_server_info=mcp_server_info)
        )

    # ── 4. Composite backend with routing ──
    if sandbox is None:
        large_results_backend = FilesystemBackend(
            root_dir=tempfile.mkdtemp(prefix="nexus_large_results_"),
            virtual_mode=True,
        )
        conversation_history_backend = FilesystemBackend(
            root_dir=tempfile.mkdtemp(prefix="nexus_conversation_history_"),
            virtual_mode=True,
        )
        composite_backend = CompositeBackend(
            default=backend,
            routes={
                "/large_tool_results/": large_results_backend,
                "/conversation_history/": conversation_history_backend,
            },
        )
    else:
        composite_backend = CompositeBackend(default=backend, routes={})

    # ── 5. Build NexusAgent graph ──
    final_checkpointer = checkpointer if checkpointer is not None else InMemorySaver()

    # Use the original graph architecture
    from workflow.graph import get_enhanced_science_graph

    graph = await get_enhanced_science_graph(checkpointer=final_checkpointer)
    logger.info("NexusAgent CLI: Using original graph architecture")

    return graph, composite_backend
