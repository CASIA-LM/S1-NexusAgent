"""planner node — initial planning and post-execution routing."""
from __future__ import annotations

import json
import logging
from datetime import datetime

from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.runnables import RunnableConfig
from langgraph.config import get_stream_writer
from langgraph.types import Command

from workflow.const import Node
from workflow.prompt import router_output
from workflow.prompt.template import apply_prompt_template
from workflow.state import WorkflowTeamState
from workflow.nodes.helpers import emit_progress, format_context
from workflow.nodes.models import get_planner_model

# Max entries of history summary injected into planner prompt to keep token cost bounded.
MAX_HISTORY_IN_CONTEXT = 8


async def planner(state: WorkflowTeamState, config: RunnableConfig):
    """Initial planning, post-execution decisions, and task completion routing."""
    writer = get_stream_writer()
    planner_model = get_planner_model()

    planner_count = state.get("planner_count", 0)
    plan_nodes = state.get("planner_steps", [])
    history_sum = state.get("history_summary", [])
    candidate_tools = state.get("candidate_tools")
    user_query = state.get("user_query", "No user question")
    last_message = state["messages"][-1]

    is_initial_plan = history_sum == [] and plan_nodes == []

    tools_desc = "\n\n---\n\n".join(
        f"## Tool Name: {t['name']}\n\n"
        f"**Tool Description:**\n"
        f"```\n{t['description'].strip()}\n```"
        for t in candidate_tools
    )

    raw_context = state.get("intent_planner_context", {})
    formatted_context_str = format_context(raw_context)

    plan_steps_content = json.dumps(
        [{"step": i + 1, "content": s.content} for i, s in enumerate(plan_nodes)],
        ensure_ascii=False,
        indent=2,
    )

    last_subtask_info = history_sum[-1] if history_sum else "First subtask, no content."
    skill_workflow = state.get("matched_skill_workflow", "")
    skill_name = state.get("matched_skill_name", "")
    if skill_name and is_initial_plan:
        logging.info(f"Planner: Using matched skill '{skill_name}' workflow as planning guidance.")

    history_for_prompt = (
        history_sum[-MAX_HISTORY_IN_CONTEXT:]
        if len(history_sum) > MAX_HISTORY_IN_CONTEXT
        else history_sum
    )

    planner_sys_prompt = await apply_prompt_template(
        Node.PLANNER,
        CURRENT_TIME=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        TOOLS_DESC=tools_desc,
        plan_steps_content=plan_steps_content,
        INTENT_CONTEXT=formatted_context_str,
        USER_QUERY=user_query,
        HISTORY_INFO=history_for_prompt,
        LAST_STEPS_INFO=last_subtask_info,
        is_initial_plan=is_initial_plan,
        SKILL_WORKFLOW=skill_workflow,
    )

    planner_messages = [
        HumanMessage(content=str(user_query)) if is_initial_plan else None,
    ]
    planner_messages = [
        m for m in [
            __import__("langchain_core.messages", fromlist=["SystemMessage"]).SystemMessage(
                content=planner_sys_prompt
            ),
            HumanMessage(content=str(user_query)),
        ]
        if m is not None
    ]
    if not is_initial_plan:
        planner_messages.append(last_message)

    MAX_PLANNER_ITERATIONS = 20
    if planner_count >= MAX_PLANNER_ITERATIONS:
        logging.warning(
            f"Planner: Reached maximum iteration count {MAX_PLANNER_ITERATIONS}, forcing to Report."
        )
        from workflow.graph import sandbox_client
        session_id = state.get("jupyter_session_id")
        if session_id:
            try:
                await sandbox_client.jupyter.delete_session(session_id=session_id)
            except Exception:
                pass
        return Command(goto=Node.REPORT, update={})

    planner_response = await planner_model.ainvoke(planner_messages)
    new_plan_steps = planner_response.nodes

    action = router_output.ActionType
    logging.info(f"planner_Router: {planner_response.action}")

    if planner_response.action == action.FINISH:
        logging.info(f"Planner Decision: FINISH. Reason: {planner_response.reasoning}")
        writer({"type": "progress", "node": "Planner", "content": "所有子任务完成，评估输出质量..."})

        from workflow.graph import sandbox_client
        session_id = state.get("jupyter_session_id")
        if session_id:
            try:
                await sandbox_client.jupyter.delete_session(session_id=session_id)
                logging.info(f"Deleted Jupyter session: {session_id}")
            except Exception as e:
                logging.warning(f"Failed to delete Jupyter session {session_id}: {e}")

        progress_msg = emit_progress("Planner", "所有子任务完成，生成报告中...")
        return Command(
            goto=Node.REPORT,
            update={
                "planner_steps": new_plan_steps,
                "subtask": "",
                "subtask_context": "",
                "subtask_expected_output": "",
                "messages": progress_msg,
                "all_messages": progress_msg,
            },
        )

    if planner_response.action == action.CALL_EXECUTOR:
        subtask = planner_response.subtask
        information = planner_response.information
        expected_output = planner_response.expected_output

        logging.info(f"Planner Agent: Dispatch subtask to executor, Subtask: {subtask}")
        writer(
            {
                "type": "subtask",
                "node": "Planner",
                "content": subtask,
                "iteration": planner_count + 1,
            }
        )

        progress_msg = emit_progress("Planner", f"分派子任务: {subtask[:100]}")
        return Command(
            goto=Node.EXECUTE,
            update={
                "subtask": subtask,
                "subtask_context": information,
                "subtask_expected_output": expected_output,
                "planner_steps": new_plan_steps,
                "planner_count": planner_count + 1,
                "messages": progress_msg,
                "all_messages": progress_msg,
            },
        )

    logging.error(f"Planner returned unknown action: {planner_response.action}")
    return Command(
        goto=Node.PLANNER,
        update={
            "history_summary": history_sum
            + [
                AIMessage(
                    content=(
                        "Last step did not make any tool calls, move on. "
                        "If the task is finished, please call the Finish tool. "
                        "Otherwise, call the CallExecutor tool to assign a subtask."
                    )
                )
            ],
            "planner_count": planner_count + 1,
        },
    )
