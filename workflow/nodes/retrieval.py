"""retrieval_tools_node — selects tools based on intent context."""
from __future__ import annotations

import logging

from langchain_core.runnables import RunnableConfig
from langgraph.config import get_stream_writer
from langgraph.types import Command

from workflow.const import Node
from workflow.state import WorkflowTeamState
from workflow.tool_retriever import ToolRetriever
from workflow.tools import base_tools, tools
from workflow.nodes.helpers import emit_progress


async def retrieval_tools_node(state: WorkflowTeamState, config: RunnableConfig):
    writer = get_stream_writer()
    context = state.get("intent_tool_retrieval_context")
    writer({"type": "progress", "node": "ToolRetrieval", "content": "正在检索相关工具..."})

    subset_tools = list(tools)

    # Load MCP tools if available
    mcp_tools = []
    try:
        from workflow.mcp.cache import get_cached_mcp_tools
        mcp_tools = get_cached_mcp_tools()
        if mcp_tools:
            logging.info(f"Loaded {len(mcp_tools)} MCP tools")
            writer(
                {
                    "type": "progress",
                    "node": "ToolRetrieval",
                    "content": f"已加载 {len(mcp_tools)} 个 MCP 工具",
                }
            )
            subset_tools.extend(mcp_tools)
    except Exception as e:
        logging.warning(f"Failed to load MCP tools: {e}")

    user_subset = state.get("user_tool_subset")
    if user_subset:
        logging.info(f"Using user-specified tool subset: {len(user_subset)} tools")
        retriever = ToolRetriever(subset_tools=user_subset)
    else:
        retriever = ToolRetriever()

    retrieval_result = await retriever.prompt_based_retrieval(context)
    selected_tools = retrieval_result["tools"]

    # Merge: base_tools + retrieved domain tools + MCP tools
    final_tool_map = {t.name: t for t in base_tools}
    for tool in selected_tools:
        final_tool_map[tool.name] = tool
    for tool in mcp_tools:
        final_tool_map[tool.name] = tool
    candidate_tools = list(final_tool_map.values())

    tool_infos = []
    for tool in candidate_tools:
        if hasattr(tool, "args_schema") and tool.args_schema:
            schema = tool.args_schema.schema()
        else:
            schema = {"properties": "check documentation"}
        tool_infos.append(
            {"name": tool.name, "description": tool.description, "parameter_schema": schema}
        )

    logging.info(
        f"Retrieved {len(candidate_tools)} tools for domain: {context.get('domain_filter')}"
    )
    tool_names = [t["name"] for t in tool_infos]
    writer(
        {
            "type": "tools",
            "node": "ToolRetrieval",
            "content": f"已检索到 {len(tool_infos)} 个工具",
            "tools": tool_names,
        }
    )

    progress_msg = emit_progress("ToolRetrieval", f"已检索到 {len(tool_infos)} 个相关工具")
    return Command(
        update={
            "candidate_tools": tool_infos,
            "messages": progress_msg,
            "all_messages": progress_msg,
        },
        goto=Node.PLANNER,
    )
