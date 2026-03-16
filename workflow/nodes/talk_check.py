"""talk_check and normal_chat nodes."""
from __future__ import annotations

from typing import Literal

from langchain_core.messages import AIMessage, SystemMessage
from langchain_core.runnables import RunnableConfig
from langgraph.config import get_stream_writer
from langgraph.types import Command

from workflow.const import Node
from workflow.prompt.template import apply_prompt_template
from workflow.prompt.unknown_general import common_system_prompt
from workflow.state import WorkflowTeamState
from workflow.nodes.helpers import (
    emit_progress,
    get_previous_messages,
    get_reset_counters,
    should_reset_task_counters,
)
from workflow.nodes.models import get_classify_model, get_normal_chat_model


async def talk_check(
    state: WorkflowTeamState, config: RunnableConfig
) -> Command[Literal["unknown_general", "unknown_intent_detect"]]:
    classify_model = get_classify_model()
    writer = get_stream_writer()
    sys_message = await apply_prompt_template(Node.TALK_CHECK)
    response = await classify_model.ainvoke(
        [SystemMessage(content=sys_message)] + get_previous_messages(state, config)
    )

    reset_counters = get_reset_counters() if should_reset_task_counters(state) else {}

    if response.small_talk:
        writer({"type": "progress", "node": "TalkCheck", "content": "闲聊模式，直接回复"})
        return Command(goto=Node.GENERAL, update=reset_counters)
    else:
        writer({"type": "progress", "node": "TalkCheck", "content": "检测为科学研究任务，开始分析..."})
        progress_msg = emit_progress("TalkCheck", "检测为科学研究任务，开始分析...")
        return Command(
            goto=Node.INTENT_DETECT,
            update={
                "messages": progress_msg,
                "all_messages": progress_msg,
                **reset_counters,
            },
        )


async def normal_chat(state: WorkflowTeamState, config: RunnableConfig):
    normal_chat_model = get_normal_chat_model()
    from typing import cast
    response = cast(
        AIMessage,
        await normal_chat_model.ainvoke(
            [SystemMessage(content=common_system_prompt)] + state.get("messages"), config
        ),
    )
    return {"messages": response}
