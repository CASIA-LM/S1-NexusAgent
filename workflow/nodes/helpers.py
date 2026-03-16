"""Shared helper utilities for all graph nodes."""
from __future__ import annotations

import json
import re
import uuid
from typing import Any, Dict, List, Optional

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.runnables import RunnableConfig

from workflow.config import Configuration
from workflow.state import WorkflowTeamState


# ---------------------------------------------------------------------------
# Progress emission helpers
# ---------------------------------------------------------------------------

def emit_progress(node_name: str, content: str) -> AIMessage:
    """Generate a progress AIMessage for CLI streaming display."""
    return AIMessage(content=f"[{node_name}] {content}", name=f"progress_{node_name}")


def emit_progress_update(node_name: str, content: str) -> Dict[str, Any]:
    """Generate a state update dict with progress message."""
    progress_msg = emit_progress(node_name, content)
    return {
        "messages": progress_msg,
        "all_messages": progress_msg,
    }


# ---------------------------------------------------------------------------
# State helpers
# ---------------------------------------------------------------------------

def get_previous_messages(state: WorkflowTeamState, config: RunnableConfig) -> list:
    from workflow.const import Flag
    configuration = Configuration.from_runnable_config(config)
    messages = []
    for message in state["messages"]:
        if message.content.find(Flag.NO_THINK) == -1 and not isinstance(message, ToolMessage):
            messages.append(message)
    return messages[-configuration.history_length:]


def should_reset_task_counters(state: WorkflowTeamState) -> bool:
    """Determine if task counters should be reset (new conversation turn)."""
    messages = state.get("messages", [])
    conversation_messages = [
        m for m in messages
        if isinstance(m, (HumanMessage, AIMessage))
        and not m.content.startswith("[")
        and not m.content.startswith("【")
    ]
    if len(conversation_messages) < 2:
        return False
    last_msg = conversation_messages[-1]
    second_last_msg = conversation_messages[-2]
    return isinstance(last_msg, HumanMessage) and isinstance(second_last_msg, AIMessage)


def get_reset_counters() -> dict:
    """Return counters/state to reset at the start of a new conversation turn."""
    return {
        "planner_count": 0,
        "codeact_interation_count": 0,
        "current_position": 0,
        "trial_count": 0,
        "jupyter_session_id": None,
        "last_executed_position": None,
        "subtask": "",
        "subtask_context": "",
        "subtask_expected_output": "",
        "previous_action_result": "",
        "previous_thought_result": "",
        "code_result_str": "",
        "history_summary": [],
        "reflection_scores": [],
        "planner_steps": [],
    }


# ---------------------------------------------------------------------------
# Context formatting helpers
# ---------------------------------------------------------------------------

def format_context(ctx: dict) -> str:
    if not ctx:
        return "No additional context, please plan based on user's original input."
    return f"""
### Core Mission
{ctx.get('mission', 'Undefined')}

### Input Data (Must strictly use the following data)
{json.dumps(ctx.get('raw_data', {}), ensure_ascii=False, indent=2)}

### Constraints (Strictly follow constraints)
{json.dumps(ctx.get('constraints', []), ensure_ascii=False, indent=2)}

### Expected Output
{json.dumps(ctx.get('target_output', []), ensure_ascii=False, indent=2)}

### Ambiguities & Notes
{json.dumps(ctx.get('ambiguities', []), ensure_ascii=False, indent=2)}
"""


def extract_contexts(intent_output) -> Dict[str, Any]:
    """Decompose IntentSchema into contexts for Tool Retriever and Planner."""
    search_queries = [intent_output.core_objective]
    for step in intent_output.key_steps:
        search_queries.append(step.description)

    retrieval_context = {
        "domain_filter": intent_output.domain,
        "search_queries": search_queries,
    }

    input_data_map = {}
    for artifact in intent_output.inputs:
        input_data_map[artifact.name] = artifact.specification

    constraints_list = [c.constraint for c in intent_output.constraints]
    ambiguities_list = intent_output.ambiguities

    planner_context = {
        "mission": intent_output.core_objective,
        "raw_data": input_data_map,
        "constraints": constraints_list,
        "ambiguities": ambiguities_list,
        "target_output": [out.name for out in intent_output.outputs],
    }

    return {
        "retrieval_context": retrieval_context,
        "planner_context": planner_context,
    }


# ---------------------------------------------------------------------------
# Tool call extraction
# ---------------------------------------------------------------------------

def _extract_tool_calls(text: str) -> List[str]:
    return re.findall(r"<tool_call>(.*?)</tool_call>", text, re.DOTALL)


def extract_tool_calls(response) -> List[Dict[str, Any]]:
    tool_calls_strs = _extract_tool_calls(response.content)
    tool_calls = []
    for tool_call_str in tool_calls_strs:
        try:
            tool_call = json.loads(tool_call_str)
        except Exception:
            continue
        tool_call["id"] = f"call_{str(uuid.uuid4())}"
        tool_call["type"] = "tool_call"
        tool_calls.append(tool_call)
    return tool_calls


# ---------------------------------------------------------------------------
# Misc utilities
# ---------------------------------------------------------------------------

def get_failed_step_content(steps: list, position: int) -> str:
    """Safely retrieve the content field of a failed step."""
    try:
        step_repr = steps[position].repr
        match = re.search(r"content=['\"](.+?)['\"]", step_repr)
        return match.group(1).strip() if match else steps[position].content
    except (IndexError, AttributeError, TypeError):
        return "N/A - Original plan step content unavailable."


async def remove_params_from_url(url: str) -> str:
    return url.split('?')[0]
