import inspect
import logging
from typing import Any, Awaitable, Callable, Optional, Sequence, Type, TypeVar, Union, Literal

from langchain_core.language_models import BaseChatModel
from langchain_core.tools import StructuredTool
from langchain_core.tools import tool as create_tool
from langgraph.graph import END, START, StateGraph
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage
from langchain_core.runnables import RunnableConfig
from langgraph.types import Command
from pydantic import BaseModel, Field
import re
from agent_sandbox import AsyncSandbox

from workflow.state import WorkflowTeamState
from workflow import config as science_config
from workflow.tools.sandbox_builtin_tools import PATH_SETUP_LINE

# ── Constants ────────────────────────────────────────────────────────────────
MAX_ITERATIONS = 15       # Hard cap on CodeAct iterations per subtask
MAX_CONTEXT_PAIRS = 8     # Sliding window: keep last N rounds of AI+Observe pairs


BACKTICK_PATTERN = r"(?:^|\n)```(.*?)(?:```(?:\n|$))"
StateSchema = TypeVar("StateSchema", bound=WorkflowTeamState)
StateSchemaType = Type[StateSchema]

DEFAULT_ERROR_OUTPUT = "代码执行失败：沙箱在运行您的代码时遇到了一个错误。请检查代码逻辑或输入数据是否正确。"

def extract_sandbox_text_with_error_handling(output) -> str:
    """
    针对 JupyterOutput 结构优化：
    跳过 traceback，仅提取核心错误名称和原因。
    """
    
    if not isinstance(output, list):
        return str(output)

    extracted_texts = []
    error_summaries = []

    for item in output:
        # 获取输出类型
        out_type = getattr(item, 'output_type', None)

        if out_type == 'error':
            # 仅提取错误名称 (ename) 和 错误原因 (evalue)
            ename = getattr(item, 'ename', 'UnknownError')
            evalue = getattr(item, 'evalue', '未知错误详情')
            
            # 格式化为：ModuleNotFoundError: No module named 'xxx'
            error_summaries.append(f"{ename}: {evalue}")
            
        elif out_type in ['stream', 'execute_result']:
            # 正常输出提取
            content = getattr(item, 'text', '') or getattr(item, 'data', '')
            if content:
                extracted_texts.append(str(content))

    # 判定：如果有报错，则只返回报错信息
    if error_summaries:
        error_info = "\n".join(error_summaries)
        return f"{DEFAULT_ERROR_OUTPUT}\n\n[错误详情]: {error_info}"

    # 如果没有报错，返回拼接的正常输出内容
    return "\n".join(extracted_texts).strip()

def extract_and_combine_codeblocks(text: str) -> str:
    """
    Extracts all codeblocks from a text string and combines them into a single code string.

    Args:
        text: A string containing zero or more codeblocks, where each codeblock is
            surrounded by triple backticks (```).

    Returns:
        A string containing the combined code from all codeblocks, with each codeblock
        separated by a newline.

    Example:
        text = '''Here's some code:

        ```python
        print('hello')
        ```
        And more:

        ```
        print('world')
        ```'''

        result = extract_and_combine_codeblocks(text)

        Result:

        print('hello')

        print('world')
    """
    # Find all code blocks in the text using regex
    # Pattern matches anything between triple backticks, with or without a language identifier
    code_blocks = re.findall(BACKTICK_PATTERN, text, re.DOTALL)

    if not code_blocks:
        return ""

    # Process each codeblock
    processed_blocks = []
    for block in code_blocks:
        # Strip leading and trailing whitespace
        block = block.strip()

        # If the first line looks like a language identifier, remove it
        lines = block.split("\n")
        if lines and (not lines[0].strip() or " " not in lines[0].strip()):
            # First line is empty or likely a language identifier (no spaces)
            block = "\n".join(lines[1:])

        processed_blocks.append(block)

    # Combine all codeblocks with newlines between them
    combined_code = "\n\n".join(processed_blocks)
    return combined_code
def extract_and_combine_execute_blocks(text: str) -> str:
    """
    Extracts all code enclosed within <execute>...</execute> tags from a text string
    and combines them into a single string.

    Args:
        text: A string potentially containing one or more <execute>...</execute> blocks.

    Returns:
        A string containing the combined code from all execute blocks, with each block
        separated by a newline, stripped of leading/trailing whitespace.
    """
    # 正则表达式：
    # 匹配 <execute> 标签
    # (.+?) 匹配中间的内容（非贪婪模式）
    # 匹配 </execute> 标签
    # re.DOTALL 确保 '.' 匹配包括换行符在内的所有字符
    pattern = r"<execute>(.*?)</execute>"
    
    # 查找所有匹配项
    execute_blocks = re.findall(pattern, text, re.DOTALL | re.IGNORECASE)

    if not execute_blocks:
        return ""

    # 处理每个提取到的代码块：去除首尾空白
    processed_blocks = [block.strip() for block in execute_blocks]

    # 使用两个换行符连接所有代码块，以保持代码块之间的逻辑分隔
    combined_code = "\n\n".join(processed_blocks)
    
    return combined_code
EvalFunction = Callable[[str, dict[str, Any]], tuple[str, dict[str, Any]]]
EvalCoroutine = Callable[[str, dict[str, Any]], Awaitable[tuple[str, dict[str, Any]]]]


# ── Sandbox client singleton ──────────────────────────────────────────────────
_sandbox_client: Optional[AsyncSandbox] = None

def _get_sandbox_client() -> AsyncSandbox:
    """Return module-level AsyncSandbox singleton (avoids reconnect on every call)."""
    global _sandbox_client
    if _sandbox_client is None:
        _sandbox_client = AsyncSandbox(base_url=science_config.SandboxConfig().base_url)
    return _sandbox_client


# ── Code executor tool ────────────────────────────────────────────────────────
class CodeExecutorInput(BaseModel):
    code: str = Field(description="The code snippet to execute")

class CodeExecutorOutput(BaseModel):
    result: str = Field(description="The output or error message from executing the code")

async def code_executor(code: str, config: RunnableConfig) -> str:
    session_id = config.get("configurable", {}).get("session_id")
    if not session_id:
        return "Error: No session_id provided in config."
    client = _get_sandbox_client()
    jupyter_result = await client.jupyter.execute_code(code=code, session_id=session_id)
    return jupyter_result.data.outputs

sandbox_code_executor_tool = StructuredTool.from_function(
    coroutine=code_executor,
    name="sandbox_code_executor",
    description="Execute python code snippets in a sandboxed jupyter environment and return the output or error messages. The sandbox have pre-installed with some libraries, call shell commands to check or install more packages if needed.",
    args_schema=CodeExecutorInput,
    metadata={
        "args_schema_json": CodeExecutorInput.schema(),
        "output_schema_json": CodeExecutorOutput.schema(),
    },
)




def create_default_prompt(tools: list[StructuredTool], base_prompt: Optional[str] = None):
    """Create default prompt for the CodeAct agent."""
    # 假设 StructuredTool 和 create_tool 存在
    # tools = [t if isinstance(t, StructuredTool) else create_tool(t) for t in tools]
    
    prompt = f"{base_prompt}\n\n" if base_prompt else ""
    prompt += """
You will be given a task to perform. You should output either
- a Python code snippet that provides the solution to the task, or a step towards the solution. Any output you want to extract from the code should be printed to the console. Code should be output in a fenced code block.
- text to be shown directly to the user, if you want to ask for more information or provide the final answer.

In addition to the Python Standard Library, you can use the following functions:
"""

    # 存储所有工具的函数签名定义部分
    function_definitions = []

#    --- 第一次循环：提取路径并生成函数体 ---
    for tool in tools:
        # 优先使用 func (同步)；如果不存在，则使用 coroutine (异步)
        callable_obj = tool.func if tool.func is not None else tool.coroutine

        # 检查 callable_obj 是否存在
        if callable_obj is None:
            logging.warning(f"Tool '{tool.name}' has neither func nor coroutine defined and will be skipped.")
            continue

        # 工具函数名称
        tool_func_name  = callable_obj.__name__
        # 工具函数路径
        tool_path = callable_obj.__module__    

        # 判断函数是同步还是异步
        is_async = inspect.iscoroutinefunction(callable_obj)

        # 获取完整签名字符串（用于函数定义展示）
        signature_str = str(inspect.signature(callable_obj))

        # 提取纯参数名列表（去掉类型注解和默认值），用于生成合法的调用示例
        _sig_params = inspect.signature(callable_obj).parameters
        _call_args = ", ".join(_sig_params.keys())

        if is_async:
            def_part = (
                f"\n# ── Tool: {tool.name} (async) ──────────────────────────────\n"
                f"# 功能: {tool.description[:150]}\n"
                f"# 签名: {tool_func_name}{signature_str}\n"
                f"# 调用方式（必须 await，禁止套 async，禁止重新定义该函数）:\n"
                f"from {tool_path} import {tool_func_name}\n"
                f"result = await {tool_func_name}({_call_args})\n"
                f"print(result)\n"
            )
        else:
            def_part = (
                f"\n# ── Tool: {tool.name} (sync) ───────────────────────────────\n"
                f"# 功能: {tool.description[:150]}\n"
                f"# 签名: {tool_func_name}{signature_str}\n"
                f"# 调用方式（禁止重新定义该函数）:\n"
                f"from {tool_path} import {tool_func_name}\n"
                f"result = {tool_func_name}({_call_args})\n"
                f"print(result)\n"
            )

        function_definitions.append(def_part)


    # --- 组合最终的 prompt ---

 
    # 加入所有工具的函数定义
    prompt += "\n".join(function_definitions)
    prompt += """
# (高优先级)请你一定注意**必须引入**下列工具所需要的依赖：
from (tool_path) import (tools_func_name)
# 如果工具函数为异步函数，请你直接await func()关键字进行直接调用，禁止使用’async‘！ 
"""
    prompt += """
# 重要执行规则 
1. **禁止依赖变量复用**：鉴于远程沙箱环境（如 Jupyter Kernel）可能因崩溃或超时而重启，**请勿依赖前一步骤中定义的任何变量或导入的模块**。
2. **强制重新导入**：为确保代码的健壮性，你在每次执行（即每个 <execute>...</execute> 代码块）时，**必须重新导入**所有需要的函数或模块（例如：`from [path] import [function]`）。
3. **输出控制**：请严格控制打印输出的大小。禁止直接打印巨大的 JSON 对象、列表或数据结构，这会导致 Kernel 崩溃，进而丢失所有状态。请只打印摘要信息、键名或使用字符串截断（如 `str(result)[:500]`）。

Reminder: use Python code snippets to call tools"""

    return prompt

def create_codeact(
    model: BaseChatModel,
    tools: Sequence[Union[StructuredTool, Callable]],
    # 移除 eval_fn，因为我们强制使用远程沙箱逻辑
    *,
    prompt: Optional[str] = None,
    state_schema: StateSchemaType = WorkflowTeamState,
) -> StateGraph:
    """Create a CodeAct agent with Remote Sandbox execution.
    """
    tools = [t if isinstance(t, StructuredTool) else create_tool(t) for t in tools]

    # if prompt is None:
    #     prompt = create_default_prompt(tools)

    is_first = False
    # Node 1: Call Model
    MAX_OUTPUT_CHARS = 3000
    
    async def call_model(state: StateSchemaType, config: RunnableConfig) -> Command[Literal["sandbox", "__end__"]]:

        messages_list = state.get("messages", [])
        current_iterations = state.get("codeact_interation_count", 0)

        # ── Hard stop: max iterations reached ────────────────────────────────
        if current_iterations >= MAX_ITERATIONS:
            logging.warning(f"CodeAct: reached MAX_ITERATIONS ({MAX_ITERATIONS}). Forcing END.")
            # Collect the last AIMessage as best-effort result
            last_ai = next(
                (m for m in reversed(messages_list) if isinstance(m, AIMessage)), None
            )
            last_observe = next(
                (m for m in reversed(messages_list) if isinstance(m, HumanMessage)
                 and "<observe>" in str(m.content)), None
            )
            fallback_parts = []
            if last_ai:
                fallback_parts.append(f"Last agent reasoning:\n{last_ai.content}")
            if last_observe:
                fallback_parts.append(f"Last execution output:\n{last_observe.content}")
            final_content = (
                f"[CodeAct stopped: reached maximum iterations ({MAX_ITERATIONS})]\n\n"
                + ("\n\n".join(fallback_parts) if fallback_parts else "No result available.")
            )
            return Command(goto=END, update={"messages": [AIMessage(content=final_content)]})

        next_iterations = current_iterations + 1

        if not messages_list:
            raise ValueError("CodeAct: state.messages is empty.")

        # ── Build context window ──────────────────────────────────────────────
        # Structure: [SystemMessage(s)] + [first HumanMessage: task]
        #            + sliding window of [AIMessage, HumanMessage(observe), ...]
        #
        # AIMessages MUST be included so the LLM can see its own prior reasoning
        # and avoid redundant re-exploration.
        try:
            system_messages = [m for m in messages_list if isinstance(m, SystemMessage)]
            non_system = [m for m in messages_list if not isinstance(m, SystemMessage)]

            # First non-system message is the task description (HumanMessage)
            first_task_msg = non_system[0] if non_system else None
            # Everything after that is the conversation: AI+Observe pairs
            conversation = non_system[1:] if len(non_system) > 1 else []

            # Apply sliding window to keep context bounded
            if len(conversation) > MAX_CONTEXT_PAIRS * 2:
                conversation = conversation[-(MAX_CONTEXT_PAIRS * 2):]

            context = system_messages + ([first_task_msg] if first_task_msg else []) + conversation
            response = await model.ainvoke(context)
        except Exception as e:
            error_msg = f"LLM Invocation Error: {str(e)}"
            return Command(update={"messages": [SystemMessage(content=error_msg)]})
        
        content = response.content
        if isinstance(content, list):
            # Concatenate textual parts; ignore tool_use or other non-text blocks
            text_parts: list[str] = []
            for block in content:
                try:
                    if isinstance(block, dict):
                        btype = block.get("type")
                        if btype in ("text", "output_text", "redacted_text"):
                            part = block.get("text") or block.get("content") or ""
                            if isinstance(part, str):
                                text_parts.append(part)
                except Exception:
                    # Be conservative; skip malformed blocks
                    continue
            msg = "".join(text_parts)
        else:
                
            # Fallback to string conversion for legacy content
            msg = str(content)

        # Enhanced parsing for better OpenAI compatibility
        # Check for incomplete tags and fix them
        if "<execute>" in msg and "</execute>" not in msg:
            msg += "</execute>"
        if "<solution>" in msg and "</solution>" not in msg:
            msg += "</solution>"
        if "<think>" in msg and "</think>" not in msg:
            msg += "</think>"

        # More flexible pattern matching for different LLM styles
        think_match = re.search(r"<think>(.*?)</think>", msg, re.DOTALL | re.IGNORECASE)
        execute_match = re.search(r"<execute>(.*?)</execute>", msg, re.DOTALL | re.IGNORECASE)
        answer_match = re.search(r"<solution>(.*?)</solution>", msg, re.DOTALL | re.IGNORECASE)

         # Alternative patterns for OpenAI models that might use different formatting
        if not execute_match:
            # Try to find code blocks that might be intended as execute blocks
            code_block_match = re.search(r"```(?:python|bash|r)?\s*(.*?)```", msg, re.DOTALL)
            if code_block_match and not answer_match:
                # If we found a code block and no solution, treat it as execute
                execute_match = code_block_match



        # 3. 解析模型输出 (同步操作，可以保留)
        #code = extract_and_combine_execute_blocks(response.content)
        code = execute_match.group(1).strip() if execute_match else ""

        # 逻辑：从完整消息中移除 <execute>...</execute> 块，剩下的部分即为文本
        if execute_match:
            # 使用 re.sub 将匹配到的整个 <execute> 块替换为空字符串
            text_content = re.sub(r"<execute>.*?</execute>", "", msg, flags=re.DOTALL | re.IGNORECASE, count=1).strip()
        else:
            text_content = msg.strip()

        # 如果有 <think> 标签，通常我们也希望从最终展示给用户的 text_content 中移除它
        text_content = re.sub(r"<think>.*?</think>", "", text_content, flags=re.DOTALL | re.IGNORECASE).strip()
        
        # 4. 更新 State
        if answer_match:
            answer = answer_match.group(1).strip()
            return Command(goto=END, update={"messages": [response], "code_agent_solution": answer})

        elif execute_match:
            # 找到下一步是沙箱执行 (sandbox)
            return Command(goto="sandbox", update={"messages": [response], "script": code, "codeact_interation_count": next_iterations})
        
        else:
            logging.error("CodeAct parsing error: no code block or final answer found in LLM response.")



    
    
    # Node 2: Remote Sandbox
    async def sandbox(state: StateSchema, config: RunnableConfig):
        """Execute the current script in the remote Jupyter sandbox."""
        script = state.get("script", "")
        # PATH_SETUP_LINE: one-liner cwd+sys.path guard (handles kernel restarts)
        final_script = PATH_SETUP_LINE + script

        try:
            output = await sandbox_code_executor_tool.ainvoke({"code": final_script}, config=config)
        except Exception as e:
            output = f"Execution Error: {str(e)}"

        output = extract_sandbox_text_with_error_handling(output)
        if len(str(output)) > MAX_OUTPUT_CHARS:
            output_str = str(output)
            output = output_str[:1500] + "\n...[Output Truncated]...\n" + output_str[-1500:]

        logging.debug(f"sandbox output ({len(str(output))} chars)")
        return {
            "messages": [{"role": "user", "content": f"<observe>{output}</observe>"}],
        }

    agent = StateGraph(state_schema)
    agent.add_node("call_model", call_model, destinations=(END, "sandbox"))
    agent.add_node("sandbox", sandbox)
    agent.add_edge(START, "call_model")
    agent.add_edge("sandbox", "call_model") 

    return agent
