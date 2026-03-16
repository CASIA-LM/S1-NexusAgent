from typing import Literal
from pydantic import BaseModel, Field


class ReportOutput(BaseModel):
    """
    报告输出结构化模型

    模型需要先判断任务复杂度，然后决定输出格式：
    - 简单任务：直接输出简要回答
    - 复杂任务：输出完整的结构化报告
    """

    # 1. 任务复杂度判断
    complexity: Literal["simple", "complex"] = Field(
        ...,
        description=(
            "任务复杂度判断。"
            "simple: 单步计算、简单查询、直接回答类问题（如数学计算、单个事实查询）。"
            "complex: 多步骤分析、需要深度推理、跨领域综合、需要详细论证的任务。"
        )
    )

    # 2. 判断理由（简短）
    reasoning: str = Field(
        ...,
        description="为什么判断为 simple 或 complex？1-2句话说明。"
    )

    # 3. 输出内容
    content: str = Field(
        ...,
        description=(
            "实际输出内容。"
            "如果 complexity='simple': 直接输出简洁的答案（1-3段文字，直接回答问题）。"
            "如果 complexity='complex': 输出完整的 Markdown 格式报告，包含："
            "# 标题、## 核心结论、## 背景与目标、## 方法与过程、## 详细结果与分析、## 结论与建议。"
        )
    )

    # 4. 标题（仅用于 complex 模式）
    title: str = Field(
        default="",
        description="报告标题。仅在 complexity='complex' 时需要填写，simple 模式留空。"
    )
