"""LLM model singletons — avoid reconstructing HTTP clients on every node call."""
from __future__ import annotations

from langchain_deepseek import ChatDeepSeek
from langchain_openai import ChatOpenAI

from workflow import config as science_config
from workflow.prompt import (
    planner_output,
    supervisor_output,
    talk_check_output,
    intent_output,
    skill_match_output,
    reflection_output,
)

_planner_model = None
_execute_model = None
_supervisor_model = None
_classify_model = None
_normal_chat_model = None
_intent_model = None
_skill_match_model = None
_reflection_model = None
_report_model = None


def get_planner_model():
    """planner node: structured plan generation."""
    global _planner_model
    if _planner_model is None:
        _planner_model = ChatDeepSeek(
            model=science_config.DeepSeekV3_2.model,
            base_url=science_config.DeepSeekV3_2.base_url,
            api_key=science_config.DeepSeekV3_2.api_key,
            temperature=0.3,
            max_tokens=8192,
        ).with_structured_output(planner_output.UnknownPlan)
    return _planner_model


def get_execute_model():
    """execute node: CodeAct ReAct loop."""
    global _execute_model
    if _execute_model is None:
        _execute_model = ChatDeepSeek(
            model=science_config.DeepSeekV3_2.model,
            base_url=science_config.DeepSeekV3_2.base_url,
            api_key=science_config.DeepSeekV3_2.api_key,
            temperature=0.3,
            max_tokens=8192,
            timeout=30,
        )
    return _execute_model


def get_supervisor_model():
    """execute node: subtask review after each step."""
    global _supervisor_model
    if _supervisor_model is None:
        _supervisor_model = ChatDeepSeek(
            model=science_config.DeepSeekV3.model,
            base_url=science_config.DeepSeekV3.base_url,
            api_key=science_config.DeepSeekV3.api_key,
            temperature=0.3,
            max_tokens=8192,
            timeout=30,
        ).with_structured_output(supervisor_output.SubtaskReview)
    return _supervisor_model


def get_classify_model():
    """talk_check node: classify small_talk vs science task."""
    global _classify_model
    if _classify_model is None:
        _classify_model = ChatDeepSeek(
            model=science_config.DeepSeekV3_2.model,
            base_url=science_config.DeepSeekV3_2.base_url,
            api_key=science_config.DeepSeekV3_2.api_key,
            temperature=0.3,
        ).with_structured_output(talk_check_output.Result)
    return _classify_model


def get_normal_chat_model():
    """normal_chat node: conversational response."""
    global _normal_chat_model
    if _normal_chat_model is None:
        _normal_chat_model = ChatDeepSeek(
            model=science_config.DeepSeekV3_2.model,
            base_url=science_config.DeepSeekV3_2.base_url,
            api_key=science_config.DeepSeekV3_2.api_key,
            temperature=science_config.DeepSeekV3_2.temperature,
            max_tokens=8192,
        )
    return _normal_chat_model


def get_intent_model():
    """intent_node: extract IntentSchema from user query."""
    global _intent_model
    if _intent_model is None:
        _intent_model = ChatDeepSeek(
            model=science_config.DeepSeekV3_2.model,
            base_url=science_config.DeepSeekV3_2.base_url,
            api_key=science_config.DeepSeekV3_2.api_key,
            temperature=0.3,
            max_tokens=4096,
        ).with_structured_output(intent_output.IntentSchema)
    return _intent_model


def get_skill_match_model():
    """skill_match_node: match user query to a skill workflow."""
    global _skill_match_model
    if _skill_match_model is None:
        _skill_match_model = ChatDeepSeek(
            model=science_config.DeepSeekV3_2.model,
            base_url=science_config.DeepSeekV3_2.base_url,
            api_key=science_config.DeepSeekV3_2.api_key,
            temperature=0.0,
            max_tokens=8192,
        ).with_structured_output(skill_match_output.SkillMatchResult)
    return _skill_match_model


def get_reflection_model():
    """reflection_node: score output quality."""
    global _reflection_model
    if _reflection_model is None:
        _reflection_model = ChatDeepSeek(
            model=science_config.DeepSeekV3_2.model,
            base_url=science_config.DeepSeekV3_2.base_url,
            api_key=science_config.DeepSeekV3_2.api_key,
            temperature=0.3,
            max_tokens=8192,
            timeout=30,
        ).with_structured_output(reflection_output.Result)
    return _reflection_model


def get_report_model():
    """report_node: generate adaptive complexity report."""
    global _report_model
    if _report_model is None:
        _report_model = ChatDeepSeek(
            model=science_config.DeepSeekV3_2.model,
            base_url=science_config.DeepSeekV3_2.base_url,
            api_key=science_config.DeepSeekV3_2.api_key,
            temperature=0.2,
            max_tokens=8192,
        )
    return _report_model
