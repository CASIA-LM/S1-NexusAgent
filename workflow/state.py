import json
import re
from dataclasses import dataclass, field
from typing import Annotated, Any, Dict
from typing import Sequence, List, Optional

from langchain_core.messages import AIMessage, AnyMessage, ToolMessage
from langchain_core.tools import BaseTool
from langgraph.graph import add_messages
from pydantic import BaseModel, Field
from typing_extensions import NotRequired, TypedDict

#from app.core.rag.qdrant import QdrantStore
# Removed Plan import from science module - not used in unknown_science
from workflow.prompt.planner_output import UnknownPlan

# from app.core.tools import managed_tools
# from app.core.tools.api_tool import dynamic_api_tool
# from app.core.tools.retriever_tool import create_retriever_tool_custom_modified
# 未知场景
from workflow.prompt.supervisor_output import SubtaskReview as Review



@dataclass
class InputState:
    """Defines the input state for the agent, representing a narrower interface to the outside world.

    This class is used to define the initial state and structure of incoming data.
    """

    messages: Annotated[Sequence[AnyMessage], add_messages] = field(
        default_factory=list
    )
    """
    Messages tracking the primary execution state of the agent.

    Typically accumulates a pattern of:
    1. HumanMessage - user input
    2. AIMessage with .tool_calls - agent picking tool(s) to use to collect information
    3. ToolMessage(s) - the responses (or errors) from the executed tools
    4. AIMessage without .tool_calls - agent responding in unstructured format to the user
    5. HumanMessage - user responds with the next conversational turn

    Steps 2-5 may repeat as needed.

    The `add_messages` annotation ensures that new messages are merged with existing ones,
    updating by ID to maintain an "append-only" state unless a message with the same ID is provided.
    """


# class GraphSkill(BaseModel):
#     name: str = Field(description="The name of the skill")
#     definition: dict[str, Any] | None = Field(
#         description="The skill definition. For api tool calling. Optional."
#     )
#     managed: bool = Field("Whether the skill is managed or user created.")

#     @property
#     def tool(self) -> BaseTool:
#         if self.managed:
#             return managed_tools[self.name].tool
#         elif self.definition:
#             return dynamic_api_tool(self.definition)
#         else:
#             raise ValueError("Skill is not managed and no definition provided.")


# class GraphUpload(BaseModel):
#     name: str = Field(description="Name of the upload")
#     description: str = Field(description="Description of the upload")
#     owner_id: int = Field(description="Id of the user that owns this upload")
#     upload_id: int = Field(description="Id of the upload")

#     @property
#     def tool(self) -> BaseTool:
#         retriever = QdrantStore().retriever(self.owner_id, self.upload_id)
#         return create_retriever_tool_custom_modified(retriever)


class GraphPerson(BaseModel):
    name: str = Field(description="The name of the person")
    role: str = Field(description="Role of the person")
    provider: str = Field(description="The provider for the llm model")
    model: str = Field(description="The llm model to use for this person")

    temperature: float = Field(description="The temperature of the llm model")
    backstory: str = Field(
        description="Description of the person's experience, motives and concerns."
    )
    agent_subgraphs: List[Any] = Field(description="工作流工具")
    agent_knowledges: List[str] = Field(description="知识库工具")
    agent_mcp_tools: List[str] = Field(description="mcp工具")
    agent_sys_tools: List[str] = Field(description="sys工具")
    knowledge_similarity: float = Field(description="知识库相似度")

    @property
    def persona(self) -> str:
        return f"<persona>\nName: {self.name}\nRole: {self.role}\nBackstory: {self.backstory}\n</persona>"


class GraphMember(GraphPerson):
    tools: list[Any] = Field(
        description="The list of tools that the person can use."
    )
    interrupt: bool = Field(
        default=False,
        description="Whether to interrupt the person or not before skill use",
    )


# Create a Leader class so we can pass leader as a team member for team within team
class GraphLeader(GraphPerson):
    pass


class GraphTeam(BaseModel):
    name: str = Field(description="The name of the team")
    role: str = Field(description="Role of the team leader")
    backstory: str = Field(
        description="Description of the team leader's experience, motives and concerns."
    )
    members: dict[str, GraphMember | GraphLeader] = Field(
        description="The members of the team"
    )
    provider: str = Field(description="The provider of the team leader's llm model")
    model: str = Field(description="The llm model to use for this team leader")

    temperature: float = Field(
        description="The temperature of the team leader's llm model"
    )

    @property
    def persona(self) -> str:
        return f"Name: {self.name}\nRole: {self.role}\nBackstory: {self.backstory}\n"


def add_or_replace_messages(
        messages: list[AnyMessage], new_messages: list[AnyMessage]
) -> list[AnyMessage]:
    """Add new messages to the state. If new_messages list is empty, clear messages instead."""
    if not new_messages:
        return []
    else:
        return add_messages(messages, new_messages)  # type: ignore[return-value, arg-type]


def format_messages(messages: list[AnyMessage]) -> str:
    """Format list of messages to string"""
    message_str: str = ""
    for message in messages:
        # 确定消息名称
        name = (
            message.name
            if message.name
            else (
                "AI"
                if isinstance(message, AIMessage)
                else "Tool" if isinstance(message, ToolMessage) else "User"
            )
        )

        # 处理消息内容为列表的情况（包含图片的消息）
        if isinstance(message.content, list):
            # 提取所有文本内容
            text_contents = []
            for item in message.content:
                if isinstance(item, dict):
                    if item.get("type") == "text":
                        text_contents.append(item.get("text", ""))
                    elif item.get("type") == "image_url":
                        text_contents.append("[图片]")
            content = " ".join(text_contents)
        else:
            content = message.content

        message_str += f"{name}: {content}\n\n"
    return message_str


def update_node_outputs(
        node_outputs: dict[str, Any], new_outputs: dict[str, Any]
) -> dict[str, Any]:
    """Update node_outputs with new outputs. If new_outputs is empty, return the original node_outputs."""
    if not new_outputs:
        return node_outputs
    else:
        return {**node_outputs, **new_outputs}


class WorkflowTeamState(TypedDict):
    all_messages: Annotated[list[AnyMessage], add_messages]
    messages: Annotated[list[AnyMessage], add_messages]
    history: Annotated[list[AnyMessage], add_messages]
    team: GraphTeam
    next: str
    main_task: list[AnyMessage]
    task: list[AnyMessage]
    node_outputs: Annotated[dict[str, Any], update_node_outputs]  # 修改这一行
    #
    chat_route: str
    current_plan: UnknownPlan | str  # Changed from Plan to UnknownPlan (science module removed)
    intent: str
    chat_clarification: bool
    science_question_slice: list
    question: str
    execute_time: int
    selected_tools: list[dict]
    reflec_time: int
    query_scene: str
    scene_messages_index: int
    # 不需要这个变量，可以直接从RunnableConfig获取
    # client_config: dict
    user_tools: list
    clarify_tool: str
    clarify_skip_check_required: bool
    reflection_message: AnyMessage
    summary_message: AnyMessage
    clarify_message: AnyMessage
    teams_info: list
    suggest_workflow: int
    is_unknown_scene: bool
    knowledge_base_search_result: dict[str, list[dict]]
    end_reason: str
    remote_tools: list
    need_clarify_tool: dict
    available_tools: dict
    test: str
    document_knowledge: str         # 文档检索总结内容

    # 未知场景用到的字段
    talk_check_prompt: str | AnyMessage | list[AnyMessage]
    is_small_talk: int
    normal_chat_prompt: str | AnyMessage | list[AnyMessage]
    normal_chat_response: str
    potential_tool_infos: list[str]
    report_prompt: str | AnyMessage | list[AnyMessage]
    potential_tool_prompt: str | AnyMessage | list[AnyMessage]
    planner_prompt: str | AnyMessage | list[AnyMessage]
    summary_prompt: str | AnyMessage | list[AnyMessage]
    supervisor_prompt: str | AnyMessage | list[AnyMessage]
    execute_prompt: str | AnyMessage | list[AnyMessage]
    reflection_prompt: str | AnyMessage | list[AnyMessage]
    planner_steps: UnknownPlan | str
    current_position: int
    reflect_message: AnyMessage | None
    max_reflection_times: int
    make_up_message: list[AnyMessage]
    needed_tools_message: AnyMessage
    extra_length: int
    locale: str
    make_up_messages: AnyMessage | None
    needed_tools: list[str]
    unknown_position: int
    candidate_tools: list[dict]
    #plan_checklist: str
    plan_checklist: Dict[str, Any] 
    args: str
    final_report_messages: AnyMessage
    report_messages: AnyMessage
    summary_output: Dict[str, Any] 
    reflection_scores: list[int]
    tools_note: str
    code_result_str: str
    executor_messages: Sequence[AnyMessage] = field(
        default_factory=list
    )
    previous_action_result: str
    previous_thought_result: str
    trial_count: int = 0 
    intent_tool_retrieval_context: Dict[str, Any]
    intent_planner_context: Dict[str, Any]
    script: Optional[str]
    """The Python code script to be executed."""
    context: dict[str, Any]
    """Dictionary containing the execution context with available tools and variables."""
    jupyter_session_id: Optional[str] 
    last_executed_position: Optional[int] # 用于判断是否切换了子任务
    planner_count: int
    subtask: str
    subtask_context: str
    subtask_expected_output: str
    sub_agent_id: str
    user_query: str

    matched_skill_name: Optional[str]
    matched_skill_workflow: Optional[str]

    script: str
    code_agent_solution: str
    codeact_interation_count: int



    # ai agent
    agent_card_id: str
    agent_query: str

    history_summary: List[Review] = field(default_factory=list)
    report_messages: AnyMessage
    summary_output: Dict[str, Any]

    # 专用模型字段
    proprietary_model_name: str  # 专有模型名称
    proprietary_model_params: dict  # 专有模型参数字典
    proprietary_model_output: dict[str, Any]  # 专有模型输出

    outline: str


# When returning teamstate, is it possible to exclude fields that you dont want to update
class ReturnWorkflowTeamState(TypedDict):
    all_messages: NotRequired[list[AnyMessage]]
    messages: NotRequired[list[AnyMessage]]
    history: NotRequired[list[AnyMessage]]
    team: NotRequired[GraphTeam]
    next: NotRequired[str | None]  # Returning None is valid for sequential graphs only
    task: NotRequired[list[AnyMessage]]
    node_outputs: Annotated[dict[str, Any], update_node_outputs]


def parse_variables(text: str, node_outputs: Dict[str, Any], is_code: bool = False) -> str:
    def replace_variable(match: re.Match) -> str:
        var_path = match.group(1).split(".")
        value: Any = node_outputs

        try:
            # 遍历变量路径，支持多层级访问
            for key in var_path:
                # 处理列表索引
                if isinstance(value, list):
                    try:
                        key = int(key)  # 尝试转换为索引
                    except ValueError:
                        # 如果列表中是字典，支持按key访问
                        pass

                # 处理字典访问
                if isinstance(value, dict) and key in value:
                    value = value[key]
                # 处理列表访问
                elif isinstance(value, list) and isinstance(key, int) and 0 <= key < len(value):
                    value = value[key]
                # 处理其他可索引类型
                elif hasattr(value, '__getitem__'):
                    value = value[key]
                else:
                    # 路径不存在，返回原始匹配
                    return match.group(0)

        except (KeyError, TypeError, IndexError, ValueError):
            return match.group(0)

        # 全角转半角处理
        def convert_fullwidth_to_halfwidth(s: Any) -> str:
            s_str = str(s) if not isinstance(s, str) else s
            result = []
            for char in s_str:
                code = ord(char)
                if 0xFF01 <= code <= 0xFF5E:
                    result.append(chr(code - 0xFEE0))
                elif code == 0x3000:
                    result.append(' ')
                else:
                    result.append(char)
            return ''.join(result)

        # 根据类型格式化输出
        if is_code:
            if isinstance(value, (dict, list, bool, int, float, type(None))):
                return json.dumps(value, ensure_ascii=False)
            else:
                converted = convert_fullwidth_to_halfwidth(value)
                return json.dumps(converted)
        else:
            if isinstance(value, (dict, list)):
                return json.dumps(value, ensure_ascii=False, indent=2)
            else:
                return convert_fullwidth_to_halfwidth(value)

    # 正则匹配变量格式 {key.path}，支持空格
    # pattern = r"\{\s*([a-zA-Z0-9_\-]+\.?[a-zA-Z0-9_\-]*)\s*\}"
    pattern = r"\{\s*([a-zA-Z0-9_\-]+(?:\.[a-zA-Z0-9_\-]+)*)\s*\}"
    return re.sub(pattern, replace_variable, text)
