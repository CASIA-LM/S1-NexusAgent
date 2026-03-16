"""多轮对话上下文优化实现。

这个模块提供了多种上下文准备策略，用于优化多轮对话中的历史消息传递。
"""

from typing import List, Literal
from langchain_core.messages import AnyMessage, HumanMessage, AIMessage, SystemMessage, ToolMessage


ContextMode = Literal["full", "smart", "last_turn_only", "sliding_window"]


def is_progress_message(message: AnyMessage) -> bool:
    """判断是否是进度消息（应该被过滤）。"""
    if not hasattr(message, "content"):
        return False
    content = str(message.content)
    return content.startswith("[") or content.startswith("【")


def extract_conversation_messages(messages: List[AnyMessage]) -> List[AnyMessage]:
    """提取真实的对话消息（用户和 AI），过滤掉进度消息和工具消息。"""
    return [
        m for m in messages
        if isinstance(m, (HumanMessage, AIMessage))
        and not is_progress_message(m)
    ]


def prepare_context_full(
    messages: List[AnyMessage],
    history_length: int = 10
) -> List[AnyMessage]:
    """完整历史模式：返回最近 N 条消息（当前默认行为）。

    Args:
        messages: 所有消息列表
        history_length: 保留的历史长度

    Returns:
        最近 N 条消息
    """
    # 过滤掉内部消息
    filtered = []
    for message in messages:
        if message.content.find("NO_THINK") == -1 and not isinstance(message, ToolMessage):
            filtered.append(message)

    return filtered[-history_length:]


def prepare_context_smart(
    messages: List[AnyMessage],
    history_length: int = 10
) -> List[AnyMessage]:
    """智能模式：添加相关性提示，让模型判断是否需要历史。

    策略：
    1. 首轮对话：直接返回当前消息
    2. 多轮对话：添加上一轮摘要 + 相关性提示 + 当前消息

    Args:
        messages: 所有消息列表
        history_length: 保留的历史长度（用于提取摘要）

    Returns:
        带相关性提示的消息列表
    """
    # 提取对话消息
    conversation = extract_conversation_messages(messages)

    # 首轮对话：直接返回
    if len(conversation) <= 1:
        return conversation

    # 当前用户消息
    current_user_msg = conversation[-1]

    # 提取上一轮的 query + answer
    if len(conversation) >= 3:
        prev_user_msg = conversation[-3]
        prev_ai_msg = conversation[-2]

        # 截断过长的内容
        prev_user_content = prev_user_msg.content[:300] if len(prev_user_msg.content) > 300 else prev_user_msg.content
        prev_ai_content = prev_ai_msg.content[:500] if len(prev_ai_msg.content) > 500 else prev_ai_msg.content

        # 构造上下文提示
        context_hint = SystemMessage(content=f"""【上一轮对话参考】
用户问题: {prev_user_content}
AI回答: {prev_ai_content}

【重要提示】
1. 如果当前问题与上一轮对话相关（如追问、深入讨论、引用上文），请利用上述历史信息
2. 如果当前问题是全新话题（如切换主题、无关问题），请忽略上述历史，专注于当前问题
3. 请根据问题的实际语义判断是否需要参考历史上下文
""")

        return [context_hint, current_user_msg]

    # 只有一轮历史：直接返回最近的消息
    return conversation[-2:]


def prepare_context_last_turn_only(
    messages: List[AnyMessage]
) -> List[AnyMessage]:
    """仅上一轮模式：只传递上一轮的 query + answer + 当前 query。

    策略：
    1. 首轮对话：直接返回当前消息
    2. 多轮对话：上一轮 user + AI + 当前 user

    Args:
        messages: 所有消息列表

    Returns:
        上一轮 + 当前轮的消息
    """
    conversation = extract_conversation_messages(messages)

    # 首轮对话
    if len(conversation) <= 1:
        return conversation

    # 多轮对话：返回最近 3 条（上一轮 user + AI + 当前 user）
    return conversation[-3:]


def prepare_context_sliding_window(
    messages: List[AnyMessage],
    window_size: int = 3
) -> List[AnyMessage]:
    """滑动窗口模式：保留最近 N 轮对话，每轮都标注。

    策略：
    1. 首轮对话：直接返回当前消息
    2. 多轮对话：添加提示 + 最近 N 轮历史 + 当前消息

    Args:
        messages: 所有消息列表
        window_size: 窗口大小（轮数）

    Returns:
        带标注的滑动窗口消息
    """
    conversation = extract_conversation_messages(messages)

    # 首轮对话
    if len(conversation) <= 1:
        return conversation

    # 计算轮次（每轮 = 1 个用户消息 + 1 个 AI 消息）
    num_turns = len(conversation) // 2

    if num_turns <= 1:
        return conversation

    # 构造带标注的历史
    result = []

    # 计算要保留的历史轮次（最多 window_size - 1 轮，为当前轮留空间）
    history_turns = min(num_turns - 1, window_size - 1)

    if history_turns > 0:
        # 添加历史提示
        context_hint = SystemMessage(content=f"""【历史对话参考】
以下是最近 {history_turns} 轮对话历史。
- 如果当前问题与历史相关，可以参考这些信息
- 如果当前问题是全新话题，请忽略历史，专注于当前问题
""")
        result.append(context_hint)

        # 计算起始索引
        start_idx = len(conversation) - 1 - (history_turns * 2)

        # 添加历史轮次
        for i in range(history_turns):
            idx = start_idx + i * 2
            if idx >= 0 and idx + 1 < len(conversation):
                result.append(conversation[idx])      # 用户消息
                result.append(conversation[idx + 1])  # AI 消息

    # 添加当前用户消息
    result.append(conversation[-1])

    return result


def prepare_context(
    messages: List[AnyMessage],
    mode: ContextMode = "smart",
    history_length: int = 10,
    window_size: int = 3
) -> List[AnyMessage]:
    """准备上下文消息（统一入口）。

    Args:
        messages: 所有消息列表
        mode: 上下文模式
            - "full": 完整历史（当前默认行为）
            - "smart": 智能摘要（推荐）
            - "last_turn_only": 仅上一轮
            - "sliding_window": 滑动窗口
        history_length: 历史长度（用于 full 模式）
        window_size: 窗口大小（用于 sliding_window 模式）

    Returns:
        准备好的上下文消息列表
    """
    if mode == "full":
        return prepare_context_full(messages, history_length)
    elif mode == "smart":
        return prepare_context_smart(messages, history_length)
    elif mode == "last_turn_only":
        return prepare_context_last_turn_only(messages)
    elif mode == "sliding_window":
        return prepare_context_sliding_window(messages, window_size)
    else:
        # 默认使用 smart 模式
        return prepare_context_smart(messages, history_length)


# ============================================================================
# 使用示例
# ============================================================================

if __name__ == "__main__":
    # 模拟多轮对话
    test_messages = [
        HumanMessage(content="什么是 BRCA1 基因？"),
        AIMessage(content="BRCA1 是一个重要的肿瘤抑制基因，位于人类第17号染色体上..."),
        HumanMessage(content="它的突变会导致什么疾病？"),
        AIMessage(content="BRCA1 基因突变会显著增加乳腺癌和卵巢癌的风险..."),
        HumanMessage(content="有哪些检测方法？"),  # 当前问题
    ]

    print("=" * 80)
    print("测试不同的上下文准备模式")
    print("=" * 80)

    # 测试 full 模式
    print("\n1. Full 模式（完整历史）:")
    result = prepare_context(test_messages, mode="full", history_length=10)
    print(f"   消息数量: {len(result)}")
    for i, msg in enumerate(result):
        print(f"   [{i}] {type(msg).__name__}: {msg.content[:50]}...")

    # 测试 smart 模式
    print("\n2. Smart 模式（智能摘要）:")
    result = prepare_context(test_messages, mode="smart")
    print(f"   消息数量: {len(result)}")
    for i, msg in enumerate(result):
        print(f"   [{i}] {type(msg).__name__}: {msg.content[:80]}...")

    # 测试 last_turn_only 模式
    print("\n3. Last Turn Only 模式（仅上一轮）:")
    result = prepare_context(test_messages, mode="last_turn_only")
    print(f"   消息数量: {len(result)}")
    for i, msg in enumerate(result):
        print(f"   [{i}] {type(msg).__name__}: {msg.content[:50]}...")

    # 测试 sliding_window 模式
    print("\n4. Sliding Window 模式（滑动窗口，窗口=2）:")
    result = prepare_context(test_messages, mode="sliding_window", window_size=2)
    print(f"   消息数量: {len(result)}")
    for i, msg in enumerate(result):
        print(f"   [{i}] {type(msg).__name__}: {msg.content[:80]}...")

    print("\n" + "=" * 80)
    print("测试完成")
    print("=" * 80)
