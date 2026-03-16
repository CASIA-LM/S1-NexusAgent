"""reflection_node and report_node."""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_core.runnables import RunnableConfig
from langgraph.config import get_stream_writer
from langgraph.types import Command

from workflow.const import Flag, Node
from workflow.prompt.template import apply_prompt_template
from workflow.state import WorkflowTeamState
from workflow.utils.minio_utils import upload_content_to_minio
from workflow.nodes.helpers import emit_progress
from workflow.nodes.models import get_reflection_model, get_report_model


async def reflection_node(state: WorkflowTeamState, config: RunnableConfig):
    reflec_model = get_reflection_model()
    plan = state["planner_steps"]
    history_sum = state.get("history_summary", [])
    user_query = state.get("user_query", "")

    sys_prompt = await apply_prompt_template(
        Node.REFLECTION,
        user_query=user_query,
        current_plan=plan,
        history_summary=history_sum,
        locale=state.get("locale", ""),
        CURRENT_TIME=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    )

    response = await reflec_model.ainvoke([HumanMessage(content=sys_prompt)])

    max_times = state.get("max_reflection_times", 0)
    reflection_scores = response.score
    reflection_thought = response.thought
    reflection_suggestion = getattr(response, "suggestion", "")

    progress_msg = emit_progress("Reflection", f"质量评估: {reflection_scores}分")

    if reflection_scores < Flag.TO_SUMMARY_SCORE and max_times < 3:
        logging.info(
            f"Reflection: score {reflection_scores} below threshold, routing to Planner (retry {max_times + 1}/3)"
        )
        feedback_entry = {
            "subtask": "[Reflection Feedback]",
            "review": {
                "abstract": reflection_thought,
                "completion_status": "needs_improvement",
            },
            "subtask_result": f"Reflection score: {reflection_scores}. Suggestion: {reflection_suggestion}",
        }
        return Command(
            goto=Node.PLANNER,
            update={
                "reflection_scores": reflection_scores,
                "max_reflection_times": max_times + 1,
                "history_summary": history_sum + [feedback_entry],
                "messages": progress_msg,
                "all_messages": progress_msg,
            },
        )

    logging.info(f"Reflection: score {reflection_scores}, proceeding to Report.")
    return Command(
        goto=Node.REPORT,
        update={
            "reflection_scores": reflection_scores,
            "messages": progress_msg,
            "all_messages": progress_msg,
        },
    )


async def report_node(state: WorkflowTeamState, config: RunnableConfig):
    writer = get_stream_writer()

    report_model = get_report_model()
    execute_his = state.get("history_summary", [])
    plan_steps = state.get("planner_steps", [])
    user_query = state["user_query"]

    writer({"type": "progress", "node": "Report", "content": "正在分析任务并生成回答..."})

    system_prompt = await apply_prompt_template(
        "unknown_summary_adaptive",
        user_query=user_query,
        plan_steps=plan_steps,
        execute_his=execute_his,
        locale=state.get("locale", "zh-CN"),
    )

    response = await report_model.ainvoke(
        [SystemMessage(content=system_prompt), HumanMessage(content="")]
    )

    # Parse adaptive JSON output
    try:
        response_text = response.content.strip()
        if "```json" in response_text:
            response_text = response_text.split("```json")[1].split("```")[0]
        elif "```" in response_text:
            response_text = response_text.split("```")[1].split("```")[0]

        result = json.loads(response_text.strip())
        complexity = result.get("complexity", "complex")
        reasoning = result.get("reasoning", "")
        report_content = result.get("content", "").strip()
        title = result.get("title", "回答") or "回答"
    except Exception as e:
        logging.error(f"Failed to parse report JSON: {e}")
        complexity = "complex"
        reasoning = "JSON parsing failed, fallback to complex mode"
        report_content = response.content.strip()
        title = "Report"
        title_match = re.search(r"^#\s+(.+)", report_content, re.MULTILINE)
        if title_match:
            title = title_match.group(1).strip()

    logging.info(f"Report complexity: {complexity}, reasoning: {reasoning}")
    logging.info(f"Report generated, length: {len(report_content)}")

    if complexity == "complex":
        file_name = f"{title.replace(' ', '_').replace('/', '-')}.md"
        url = await upload_content_to_minio(
            content=report_content, file_name=file_name, content_type="text/markdown"
        )
        summary_output = {"title": title, "url": url}
        writer({"type": "report", "node": "Report", "content": report_content, "title": title, "url": url})
    else:
        summary_output = {"title": title, "url": ""}
        writer({"type": "report", "node": "Report", "content": report_content, "title": title, "url": ""})

    return {
        "messages": [
            emit_progress("Report", "回答生成完成"),
            AIMessage(content=json.dumps(summary_output, ensure_ascii=False)),
        ],
        "all_messages": [
            emit_progress("Report", "回答生成完成"),
            AIMessage(content=json.dumps(summary_output, ensure_ascii=False)),
        ],
        "summary_output": summary_output,
        "extra_length": 0,
        "current_position": 0,
        "report_messages": report_content,
        "planner_steps": [],
        "user_query": "",
        "candidate_tools": [],
    }
