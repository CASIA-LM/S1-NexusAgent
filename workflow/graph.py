"""NexusAgent LangGraph workflow — graph building only.

Node implementations live in workflow/nodes/.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import datetime
from typing import Any, Dict, Optional

# ── Langfuse Tracing ──────────────────────────────────────────────────────────
# Configure via environment variables before importing langfuse.
# To enable tracing, set the following in your .env:
#   LANGFUSE_SECRET_KEY=sk-lf-...
#   LANGFUSE_PUBLIC_KEY=pk-lf-...
#   LANGFUSE_BASE_URL=https://cloud.langfuse.com   (or your self-hosted URL)
_LANGFUSE_ENABLED = False
try:
    _secret = os.environ.get("LANGFUSE_SECRET_KEY", "")
    _public = os.environ.get("LANGFUSE_PUBLIC_KEY", "")
    _base_url = os.environ.get("LANGFUSE_BASE_URL", "https://cloud.langfuse.com")

    if _secret and _public:
        from langfuse.langchain import CallbackHandler as LangfuseCallbackHandler
        _LANGFUSE_ENABLED = True
except ImportError:
    pass

from langchain_core.messages import AnyMessage, HumanMessage
from langchain_core.load import dumpd
from langchain_core.runnables import RunnableConfig
from langgraph.graph import StateGraph, START, END

from workflow.config import Configuration, SandboxConfig
from workflow.const import Node
from workflow.state import WorkflowTeamState, InputState
from workflow.nodes import (
    talk_check,
    normal_chat,
    intent_node,
    skill_match_node,
    retrieval_tools_node,
    planner,
    execute,
    reflection_node,
    report_node,
)

from agent_sandbox import AsyncSandbox

LOGGER_LEVEL = os.getenv("LOGGER_LEVEL", "INFO")

logging.basicConfig(
    level=getattr(logging, LOGGER_LEVEL),
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(
            os.path.join(os.path.dirname(__file__), "..", "nexus_agent.log"),
            encoding="utf-8",
        ),
    ],
)

# Sandbox client — shared across execute node calls
sandbox_client = AsyncSandbox(base_url=SandboxConfig().base_url)


# ── Langfuse helpers ──────────────────────────────────────────────────────────

def create_langfuse_callbacks(
    session_id: str = "default",
    user_id: Optional[str] = None,
    tags: Optional[list] = None,
) -> list:
    """Return Langfuse callback list if tracing is enabled, else empty list."""
    if not _LANGFUSE_ENABLED:
        return []
    handler = LangfuseCallbackHandler(
        secret_key=os.environ.get("LANGFUSE_SECRET_KEY"),
        public_key=os.environ.get("LANGFUSE_PUBLIC_KEY"),
        host=os.environ.get("LANGFUSE_BASE_URL", "https://cloud.langfuse.com"),
        session_id=session_id,
        user_id=user_id,
        tags=tags or [],
    )
    return [handler]


def get_traced_run_config(
    base_config: Optional[Dict[str, Any]] = None,
    session_id: str = "default",
    user_id: Optional[str] = None,
    tags: Optional[list] = None,
) -> Dict[str, Any]:
    """Merge Langfuse callbacks into a run config dict."""
    cfg = base_config or {}
    callbacks = create_langfuse_callbacks(session_id=session_id, user_id=user_id, tags=tags)
    if callbacks:
        cfg["callbacks"] = callbacks
    return cfg


# ── Graph builders ────────────────────────────────────────────────────────────

async def get_unknown_science_graph():
    """Build and compile the base NexusAgent graph (no persistence)."""
    science_graph = StateGraph(WorkflowTeamState, input=InputState, config_schema=Configuration)

    science_graph.add_node(Node.TALK_CHECK, talk_check)
    science_graph.add_node(Node.GENERAL, normal_chat)
    science_graph.add_node(Node.INTENT_DETECT, intent_node)
    science_graph.add_node(Node.SKILL_MATCH, skill_match_node)
    science_graph.add_node(Node.RETRIEVAL_TOOLS, retrieval_tools_node)
    science_graph.add_node(Node.PLANNER, planner)
    science_graph.add_node(Node.EXECUTE, execute)
    science_graph.add_node(Node.REPORT, report_node)

    science_graph.add_edge(START, Node.TALK_CHECK)
    science_graph.add_edge(Node.REPORT, END)
    science_graph.add_edge(Node.GENERAL, END)

    return science_graph.compile()


async def get_enhanced_science_graph(checkpointer=None):
    """Build the NexusAgent graph with optional checkpointer for multi-turn CLI support.

    Args:
        checkpointer: LangGraph checkpointer for session persistence.
            Pass ``None`` for single-turn (stateless) operation.
    """
    science_graph = StateGraph(WorkflowTeamState, input=InputState, config_schema=Configuration)

    science_graph.add_node(Node.TALK_CHECK, talk_check)
    science_graph.add_node(Node.GENERAL, normal_chat)
    science_graph.add_node(Node.INTENT_DETECT, intent_node)
    science_graph.add_node(Node.SKILL_MATCH, skill_match_node)
    science_graph.add_node(Node.RETRIEVAL_TOOLS, retrieval_tools_node)
    science_graph.add_node(Node.PLANNER, planner)
    science_graph.add_node(Node.EXECUTE, execute)
    science_graph.add_node(Node.REPORT, report_node)

    science_graph.add_edge(START, Node.TALK_CHECK)
    science_graph.add_edge(Node.REPORT, END)
    science_graph.add_edge(Node.GENERAL, END)

    if checkpointer is not None:
        return science_graph.compile(checkpointer=checkpointer)
    return science_graph.compile()
