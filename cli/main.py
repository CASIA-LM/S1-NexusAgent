"""NexusAgent CLI entry point.

Mirrors deepagents_cli.main.run_textual_cli_async() but replaces the agent
creation step with our NexusAgent graph. Reuses the Deep Agents CLI's
MCP loading, session management, and Textual app infrastructure.
"""

from __future__ import annotations

import logging
import sys
import uuid
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


# Custom S1-NexusAgent banner
_NEXUS_UNICODE_BANNER = """
 ███████╗ ██╗       ███╗   ██╗ ███████╗ ██╗  ██╗ ██╗   ██╗ ███████╗
 ██╔════╝███║       ████╗  ██║ ██╔════╝ ╚██╗██╔╝ ██║   ██║ ██╔════╝
 ███████╗╚██║ █████╗██╔██╗ ██║ █████╗    ╚███╔╝  ██║   ██║ ███████╗
 ╚════██║ ██║ ╚════╝██║╚██╗██║ ██╔══╝    ██╔██╗  ██║   ██║ ╚════██║
 ███████║ ██║       ██║ ╚████║ ███████╗ ██╔╝ ██╗ ╚██████╔╝ ███████║
 ╚══════╝ ╚═╝       ╚═╝  ╚═══╝ ╚══════╝ ╚═╝  ╚═╝  ╚═════╝  ╚══════╝

  █████╗   ██████╗  ███████╗ ███╗   ██╗ ████████╗ ███████╗
 ██╔══██╗ ██╔════╝  ██╔════╝ ████╗  ██║ ╚══██╔══╝ ██╔════╝
 ███████║ ██║  ███╗ █████╗   ██╔██╗ ██║    ██║    ███████╗
 ██╔══██║ ██║   ██║ ██╔══╝   ██║╚██╗██║    ██║    ╚════██║
 ██║  ██║ ╚██████╔╝ ███████╗ ██║ ╚████║    ██║    ███████║
 ╚═╝  ╚═╝  ╚═════╝  ╚══════╝ ╚═╝  ╚═══╝    ╚═╝    ╚══════╝
                                          AI4Science v1.0
"""

_NEXUS_ASCII_BANNER = """
  ____  _        _   _  _____  __  __  _   _  ____
 / ___|| |      | \\ | || ____| \\ \\/ / | | | |/ ___|
 \\___ \\| |_____ |  \\| ||  _|    \\  /  | | | |\\___ \\
  ___) | |_____|_| |\\  || |___   /  \\  | |_| | ___) |
 |____/|_|      |_| \\_||_____| /_/\\_\\  \\___/ |____/

    _    ____  ____  _   _  _____  ____
   / \\  / ___|| ___|| \\ | ||_   _|/ ___|
  / _ \\| |  _ | |_  |  \\| |  | |  \\___ \\
 / ___ \\ |_| ||  _| | |\\  |  | |   ___) |
/_/   \\_\\____||____||_| \\_|  |_|  |____/
                             AI4Science v1.0
"""


def _patch_banner() -> None:
    """Replace DeepAgents banner with S1-NexusAgent banner."""
    try:
        from deepagents_cli import config as deepagents_config

        def get_nexus_banner() -> str:
            """Get S1-NexusAgent banner based on charset mode."""
            from deepagents_cli.config import CharsetMode, _detect_charset_mode

            if _detect_charset_mode() == CharsetMode.ASCII:
                return _NEXUS_ASCII_BANNER
            else:
                return _NEXUS_UNICODE_BANNER

        # Replace the banner function
        deepagents_config.get_banner = get_nexus_banner
    except ImportError:
        logger.debug("Could not patch banner - deepagents_cli not available")


async def _load_mcp_tools(
    mcp_config_path: str | None,
    no_mcp: bool,
    trust_project_mcp: bool | None = None,
) -> tuple[list, Any, Any]:
    """Load MCP tools using Deep Agents CLI's resolver.

    Returns:
        3-tuple of (mcp_tools, mcp_session_manager, mcp_server_info).
        All empty/None if MCP is disabled or unavailable.
    """
    try:
        from deepagents_cli.mcp_tools import resolve_and_load_mcp_tools

        return await resolve_and_load_mcp_tools(
            explicit_config_path=mcp_config_path,
            no_mcp=no_mcp,
            trust_project_mcp=trust_project_mcp,
        )
    except ImportError:
        logger.debug("MCP tools not available")
        return [], None, None
    except FileNotFoundError as e:
        logger.warning("MCP config file not found: %s", e)
        return [], None, None
    except RuntimeError as e:
        logger.warning("Failed to load MCP tools: %s", e)
        return [], None, None


async def run_nexus_cli_async(
    assistant_id: str = "nexus",
    *,
    auto_approve: bool = False,
    thread_id: str | None = None,
    initial_prompt: str | None = None,
    mcp_config_path: str | None = None,
    no_mcp: bool = False,
    trust_project_mcp: bool | None = None,
    enable_conversation_log: bool = True,
) -> Any:
    """Run the NexusAgent CLI.

    This is the async entry point that:
    1. Loads MCP tools (optional)
    2. Creates the NexusAgent graph via create_nexus_cli_agent()
    3. Launches the NexusAgentsApp (Textual UI)

    Args:
        assistant_id: Agent identifier for memory/state storage.
        auto_approve: Skip HITL approval prompts.
        thread_id: Thread ID for session persistence (new or resumed).
        initial_prompt: Auto-submit this prompt when session starts.
        mcp_config_path: Path to MCP servers JSON configuration file.
        no_mcp: Disable all MCP tool loading.
        trust_project_mcp: Controls project-level stdio server trust.
        enable_conversation_log: Enable automatic conversation logging.

    Returns:
        AppResult with return code and final thread ID.
    """
    # Patch the banner before importing DeepAgentsApp
    _patch_banner()

    from deepagents_cli.config import console, settings

    # Display startup info
    console.print("[bold green]🔬 S1-NexusAgent CLI[/bold green]", highlight=False)
    console.print("[dim]AI4Science Research Assistant[/dim]", highlight=False)
    console.print()

    # Thread management
    if thread_id is None:
        thread_id = str(uuid.uuid4())
    console.print(f"[dim]Thread: {thread_id}[/dim]", highlight=False)

    # Load MCP tools
    mcp_tools, mcp_session_manager, mcp_server_info = await _load_mcp_tools(
        mcp_config_path, no_mcp, trust_project_mcp
    )

    # Get checkpointer for session persistence
    from deepagents_cli.sessions import get_checkpointer

    async with get_checkpointer() as checkpointer:
        # Create the NexusAgent (our graph as primary agent)
        from cli.nexus_agent import create_nexus_cli_agent

        try:
            agent, composite_backend = await create_nexus_cli_agent(
                assistant_id=assistant_id,
                checkpointer=checkpointer,
                auto_approve=auto_approve,
                mcp_server_info=mcp_server_info,
            )
        except Exception as e:
            logger.exception("Failed to create NexusAgent")
            console.print(f"[bold red]Error:[/bold red] Failed to create agent: {e}")
            sys.exit(1)

        # Run the NexusAgentsApp (inherits DeepAgentsApp's full UI)
        from cli.app import NexusAgentsApp

        app = NexusAgentsApp(
            agent=agent,
            assistant_id=assistant_id,
            backend=composite_backend,
            auto_approve=auto_approve,
            cwd=Path.cwd(),
            thread_id=thread_id,
            initial_prompt=initial_prompt,
            checkpointer=checkpointer,
            mcp_server_info=mcp_server_info,
            enable_conversation_log=enable_conversation_log,
        )

        result = await app.run_async()

        # Cleanup MCP sessions
        if mcp_session_manager:
            try:
                await mcp_session_manager.close()
            except Exception:
                logger.debug("MCP session cleanup failed", exc_info=True)

        return result
