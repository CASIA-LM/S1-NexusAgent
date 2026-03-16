"""execute node — runs CodeAct ReAct loop for a single subtask."""
from __future__ import annotations

import json
import logging
import uuid
from typing import Any, Dict

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.memory import MemorySaver
from langgraph.config import get_stream_writer
from langgraph.types import Command

from workflow.codeact_remote import create_codeact, create_default_prompt
from workflow.const import Node
from workflow.prompt.sandbox_execution import get_sandbox_execution_prompt
from workflow.prompt.template import apply_prompt_template
from workflow.state import WorkflowTeamState
from workflow.tools import tools
from workflow.tools.sandbox_builtin_tools import SANDBOX_TOOLS_PY, BUILTIN_TOOLS_PROMPT
from workflow.nodes.helpers import emit_progress
from workflow.nodes.models import get_execute_model, get_supervisor_model


def _initialize_code_agent(execute_model, unique_tools):
    code_act = create_codeact(execute_model, unique_tools)
    return code_act.compile(checkpointer=MemorySaver())


async def execute(state: WorkflowTeamState, config: RunnableConfig):
    """Execute ReAct logic for current subtask."""
    from workflow.graph import sandbox_client

    writer = get_stream_writer()
    current_session_id = state.get("jupyter_session_id")
    current_task = state["subtask"]
    current_context = state["subtask_context"]
    current_expected_output = state["subtask_expected_output"] or "Concise task solving result."
    history_sum = state.get("history_summary", [])
    user_query = state.get("user_query", "No user question")

    # Session management
    if current_session_id:
        session_id = current_session_id
        logging.info(f"Reuse existing Session ID: {session_id}")
    else:
        session_id = str(uuid.uuid4())
        session_response = await sandbox_client.jupyter.create_session(session_id=session_id)
        current_session_id = session_response.data.session_id
        logging.info(f"Create new Session ID for new subtask: {current_session_id}")
        # ── Built-in tools bootstrap (new session only) ───────────────────────
        # 1. Write sandbox_tools.py to /home/work so it's importable from Jupyter
        try:
            await sandbox_client.file.write_file(
                file="/home/work/sandbox_tools.py",
                content=SANDBOX_TOOLS_PY,
                encoding="utf-8",
            )
            logging.info("sandbox_tools.py written to /home/work/")
        except Exception as _e:
            logging.warning(f"Failed to write sandbox_tools.py: {_e}")
        # 2. One-time Jupyter setup: set cwd + sys.path (survives as kernel state)
        try:
            await sandbox_client.jupyter.execute_code(
                code=(
                    'import os,sys\n'
                    'os.chdir("/home/work")\n'
                    '"/home/work" not in sys.path and sys.path.insert(0,"/home/work")\n'
                    'print("[sandbox] cwd:", os.getcwd(), "| path ok:", "/home/work" in sys.path)'
                ),
                session_id=current_session_id,
            )
            logging.info("Jupyter session one-time setup complete.")
        except Exception as _e:
            logging.warning(f"Jupyter one-time setup failed: {_e}")

    plan_nodes = state.get("planner_steps", [])
    candidate_tools = state.get("candidate_tools", [])

    # Resolve StructuredTool objects from candidate metadata
    candidate_tools_structured = []
    for tool_meta in candidate_tools:
        for t in tools:
            if tool_meta["name"] == t.name:
                candidate_tools_structured.append(t)
                break
    unique_tools = list({t.name: t for t in candidate_tools_structured}.values())

    execute_model = get_execute_model()
    abs_model = get_supervisor_model()

    execute_sys_prompt = await apply_prompt_template(
        "unknown_executor",
        user_query=user_query,
        history_sum=history_sum,
        plan_nodes=plan_nodes,
        locale=state.get("locale", ""),
    )

    system_prompt = create_default_prompt(unique_tools, execute_sys_prompt)
    system_prompt += "\n\n" + BUILTIN_TOOLS_PROMPT

    # Inject matched skill workflow
    matched_skill_workflow = state.get("matched_skill_workflow", "")
    matched_skill_name = state.get("matched_skill_name", "")
    if matched_skill_workflow:
        logging.info(f"Execute: Injecting skill '{matched_skill_name}' workflow into system prompt.")
        system_prompt += (
            f"\n\n## 技能工作流指导（来自 Skill: {matched_skill_name}）\n{matched_skill_workflow}"
        )

    system_prompt += "\n\n" + get_sandbox_execution_prompt()
    system_prompt += "\n\n## IMPORTANT FOR GPT MODELS\nYou MUST use XML tags <execute> or <solution> in EVERY response."
    system_prompt += (
        "\n\n## Strict Execution Rules (CRITICAL EXECUTION RULES):\n"
        "1. **Code Execution:** Only when code needs to be run wrap the Python code block with <execute>...</execute>.\n"
        "2. **Task Completion:** When the final answer is found, use <solution>...</solution>.\n"
        "3. **Mutual Exclusivity:** Never use both <execute> and <solution> in the same response.\n"
        "4. **Every Response Must Use Tags:** Every response must contain one <execute> or one <solution> tag.\n"
        "5. **Target Language:** Chinese (zh-cn)\n"
        "6. **File Operations:** All output files MUST be saved to /home/gem/outputs/directory.\n"
        "7. **Python Package Installation Prohibited:** Do not install missing python packages.\n"
        "8. **No Markdown Headers in solution:** Use bold (**text**) instead of # headings.\n"
    )


    code_agent = _initialize_code_agent(execute_model, unique_tools)

    parent_thread_id = config.get("configurable", {}).get("thread_id", "default")
    parent_callbacks = config.get("callbacks", [])
    run_config = {
        "configurable": {
            "thread_id": f"{parent_thread_id}_subtask_{str(uuid.uuid4())[:8]}",
            "session_id": current_session_id,
        },
        "callbacks": parent_callbacks,
    }

    # Build compact summary of prior subtask results
    if history_sum:
        prior_parts = []
        for i, entry in enumerate(history_sum, 1):
            status = entry.get("review", {}).get("completion_status", "unknown")
            abstract = entry.get("review", {}).get("abstract", "")[:300]
            subtask_desc = entry.get("subtask", "")
            prior_parts.append(f"  Step {i} [{status}]: {subtask_desc}\n    Result: {abstract}")
        prior_results_summary = "\n".join(prior_parts)
    else:
        prior_results_summary = "None (this is the first subtask)."

    current_task_content = (
        f"## Prior subtasks summary:\n{prior_results_summary}\n"
        f"## Task background information:\n{current_context}\n"
        f"## Expected output format and content:\n{current_expected_output}\n"
        f"## Current subtask:\n{current_task}"
    )

    input_messages = [
        SystemMessage(content=system_prompt),
        HumanMessage(content=current_task_content),
    ]

    writer({"type": "execute_start", "node": "Execute", "content": current_task})

    _last_msg_count = 0
    final_step_content = {}

    async for typ, chunk in code_agent.astream(
        {"messages": input_messages},
        stream_mode=["values", "messages"],
        config=run_config,
    ):
        if typ == "messages":
            if chunk and isinstance(chunk[0], Dict):
                content_chunk = chunk[0].get("content", "")
            else:
                content_chunk = chunk[0].content if hasattr(chunk[0], "content") else ""
            if content_chunk:
                writer({"type": "execute_stream", "node": "Execute", "content": content_chunk})

        if typ == "values":
            final_step_content = chunk
            messages = chunk.get("messages", [])
            if len(messages) > _last_msg_count:
                for msg in messages[_last_msg_count:]:
                    msg_text = msg.content if hasattr(msg, "content") else str(msg)
                    if isinstance(msg, HumanMessage) and "<observe>" in str(msg_text):
                        writer({"type": "execute_stream", "node": "Execute", "content": str(msg_text)})
                _last_msg_count = len(messages)

    messages_list = final_step_content.get("messages", [])

    # Extract final result
    if messages_list:
        code_agent_solution = final_step_content.get("code_agent_solution", "")
        if code_agent_solution:
            result = code_agent_solution
        else:
            last_ai = next((m for m in reversed(messages_list) if isinstance(m, AIMessage)), None)
            last_observe = next(
                (
                    m
                    for m in reversed(messages_list)
                    if isinstance(m, HumanMessage) and "<observe>" in str(m.content)
                ),
                None,
            )
            parts = []
            if last_ai:
                parts.append(last_ai.content)
            if last_observe:
                parts.append(str(last_observe.content))
            result = "\n".join(parts) if parts else str(messages_list[-1].content)

        subtask_result = (
            f"## Subtask execution result:\n"
            f"** Subtask: {current_task}\n\n"
            f"** Subtask result: {result}\n"
        )
    else:
        logging.warning("Execute: messages list is empty.")
        subtask_result = "No execution output."

    writer({"type": "execute_done", "node": "Execute", "content": subtask_result[:500]})
    final_message = AIMessage(content=subtask_result)

    # Supervisor review
    if messages_list:
        summarize_content_parts = []
        for msg in messages_list:
            if isinstance(msg, AIMessage):
                summarize_content_parts.append(f"Agent Action/Thought: {msg.content}")
            elif isinstance(msg, HumanMessage):
                msg_text = str(msg.content)
                if "<observe>" in msg_text:
                    summarize_content_parts.append(f"Observation/Code Output: {msg_text}")
        full_execution_log = "\n---\n".join(summarize_content_parts)

        sys_prompt_supervisor = await apply_prompt_template(
            Node.SUPERVISOR,
            subtask=current_task,
            full_execution_log=full_execution_log,
            subtask_result=subtask_result,
            locale=state.get("locale", ""),
        )
        try:
            review = await abs_model.ainvoke([SystemMessage(content=sys_prompt_supervisor)])
            if review:
                history_sum.append(
                    {
                        "subtask": current_task,
                        "review": review.model_dump(),
                        "subtask_result": (
                            subtask_result
                            if len(subtask_result) < 2000
                            else subtask_result[:1000] + "..."
                        ),
                    }
                )
        except Exception as e:
            logging.error(f"Supervisor call failed: {e}")
            history_sum.append(
                {
                    "subtask": current_task,
                    "review": {
                        "abstract": "Summary model call failed.",
                        "completion_status": "failed",
                        "next_step_suggestion": "Supervisor failed; Planner should re-evaluate.",
                    },
                }
            )

    return Command(
        goto=Node.PLANNER,
        update={
            "messages": [final_message],
            "previous_action_result": subtask_result,
            "trial_count": 0,
            "jupyter_session_id": current_session_id,
            "history_summary": history_sum,
            "codeact_interation_count": 0,
        },
    )
