"""intent_node, skill_match_node, identify_language_node."""
from __future__ import annotations

import logging

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.runnables import RunnableConfig
from langgraph.config import get_stream_writer
from langgraph.types import Command

from workflow.const import Node
from workflow.prompt import identify_language_output
from workflow.prompt import intent_output
from workflow.prompt.template import apply_prompt_template
from workflow.skills.integration import get_skill_manager
from workflow.state import WorkflowTeamState
from workflow.nodes.helpers import emit_progress, extract_contexts
from workflow.nodes.models import get_intent_model, get_skill_match_model


async def identify_language_node(state: WorkflowTeamState, config: RunnableConfig):
    # Currently returns zh-CN directly; language detection model can be wired in later.
    return Command(goto=Node.RETRIEVAL_TOOLS, update={"locale": "zh-CN"})


async def intent_node(state: WorkflowTeamState, config: RunnableConfig):
    intent_model = get_intent_model()
    writer = get_stream_writer()
    intent_sys_prompt = await apply_prompt_template(Node.INTENT_DETECT)

    user_query = "No user question"
    for msg in reversed(state["messages"]):
        if isinstance(msg, HumanMessage):
            user_query = str(msg.content)
            break

    writer({"type": "progress", "node": "Intent", "content": "正在解析任务意图..."})
    response = await intent_model.ainvoke(
        [SystemMessage(content=intent_sys_prompt), HumanMessage(content=user_query)]
    )
    contexts = extract_contexts(intent_output=response)

    logging.info(f"user_query: {user_query}")
    logging.info(f"intent_detect: {contexts}")
    writer(
        {
            "type": "progress",
            "node": "Intent",
            "content": f"意图解析完成: {contexts['planner_context'].get('mission', user_query)[:80]}",
        }
    )

    progress_msg = emit_progress(
        "Intent",
        f"意图解析完成：{contexts['planner_context'].get('core_objective', user_query)[:80]}",
    )
    return Command(
        goto=Node.SKILL_MATCH,
        update={
            "intent_tool_retrieval_context": contexts["retrieval_context"],
            "intent_planner_context": contexts["planner_context"],
            "user_query": user_query,
            "messages": progress_msg,
            "all_messages": progress_msg,
        },
    )


async def skill_match_node(state: WorkflowTeamState, config: RunnableConfig):
    """Progressive skill matching: lightweight metadata scan → full workflow on match."""
    writer = get_stream_writer()
    skill_manager = get_skill_manager()
    skills_prompt = skill_manager.format_skills_for_prompt(enabled_only=True)

    if not skills_prompt:
        logging.info("Skill Match: No enabled skills available, skipping.")
        writer({"type": "progress", "node": "SkillMatch", "content": "未找到可用的技能，跳过技能匹配"})
        return Command(goto=Node.RETRIEVAL_TOOLS, update={})

    user_query = state.get("user_query", "")
    writer({"type": "progress", "node": "SkillMatch", "content": "正在匹配专业技能工作流..."})

    match_model = get_skill_match_model()
    skill_match_sys_prompt = await apply_prompt_template(
        Node.SKILL_MATCH, SKILLS_LIST=skills_prompt
    )
    match_response = await match_model.ainvoke(
        [SystemMessage(content=skill_match_sys_prompt), HumanMessage(content=user_query)]
    )

    logging.info(
        f"Skill Match Result: matched_skill={match_response.matched_skill}, "
        f"reasoning={match_response.reasoning}"
    )

    if match_response.matched_skill:
        skill = skill_manager.get_skill(match_response.matched_skill)
        if skill:
            logging.info(
                f"Skill Match: Loaded full workflow for skill '{skill.metadata.name}' "
                f"({len(skill.workflow)} chars)"
            )
            writer({"type": "progress", "node": "SkillMatch", "content": f"匹配到技能: {skill.metadata.name}"})
            progress_msg = emit_progress("SkillMatch", f"匹配到技能工作流: {skill.metadata.name}")
            return Command(
                goto=Node.RETRIEVAL_TOOLS,
                update={
                    "matched_skill_name": skill.metadata.name,
                    "matched_skill_workflow": skill.workflow,
                    "messages": progress_msg,
                    "all_messages": progress_msg,
                },
            )

    writer({"type": "progress", "node": "SkillMatch", "content": "未匹配到合适的技能工作流"})
    return Command(goto=Node.RETRIEVAL_TOOLS, update={})
