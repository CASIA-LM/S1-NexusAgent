from pydantic import BaseModel, Field
from typing import Literal

class PlanReview(BaseModel):
    """
    用于存储和传递 LangGraph 中单个已执行计划步骤的审查结果和摘要信息。
    """
    
    # 步骤在原始计划列表中的索引 (从 0 开始)
    step_index: int = Field(
        ..., 
        description="该 Review 对应的计划步骤在 'planner_steps' 列表中的索引（从 0 开始）。"
    )
    
    # 原始计划步骤的内容
    content: str = Field(
        ..., 
        description="该步骤的原始内容或指令。"
    )
    
    # 由 LLM 对执行结果生成的摘要
    abstract: str = Field(
        ..., 
        description="LLM 对该步骤工具调用或执行结果生成的简洁摘要。这部分信息将被用于后续计划的上下文。"
    )
    
    # 步骤的执行状态 (用于决策是否需要 Replan)
    invoke_status: Literal["success", "failed"] = Field(
        ...,
        description="该步骤的执行状态。必须是 'SUCCESS' 或 'FAIL'。"
    )