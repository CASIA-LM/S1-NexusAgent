
from typing import Literal
from pydantic import Field, BaseModel

class SubtaskReview(BaseModel):
    """用于总结整个子任务执行结果的结构，供上层Planner参考。"""

    # 1. 核心总结 (保留并优化描述)
    abstract: str = Field(
        description="针对整个子任务执行过程的简洁摘要。内容应包括：**执行的最终结论、关键数据或发现**，以及**是否成功解决了子任务**。",
    )
    
    # 2. 状态评估 (从工具调用状态升级为子任务完成状态)
    completion_status: Literal["completed", "partial_success", "failed"] = Field(
        description="对当前子任务完成度的评估：'completed' (任务目标达成)；'partial_success' (部分结果达成，但存在遗留问题或数据不全)；'failed' (任务失败或无法继续)。",
    )
    
    # 3. 规划建议/遗留问题 (新增，对 Planner 至关重要)
    # next_step_suggestion: str = Field(
    #     description="基于当前子任务的执行结果，为Planner提供的下一步行动建议。如果任务已完成，请说明下一步可以做什么；如果遇到困难，请具体说明下一步应如何调整或获取缺失的信息。",
    # )

    class Config:
        json_schema_extra = {
            "examples": [
                {
                    "abstract": "成功使用 `scRNA_analysis` 工具完成了细胞聚类和可视化，关键发现是第3类细胞表达高水平的marker X。",
                    "completion_status": "completed",
                    #"next_step_suggestion": "此子任务已完成。Planner下一步应根据用户要求，撰写最终报告或继续执行后续的数据解释任务。",
                },
                {
                    "abstract": "尝试执行数据预处理，但发现输入数据格式与预期不符（缺少关键列Y）。代码执行失败。",
                    "completion_status": "failed",
                    #"next_step_suggestion": "Planner应调整下一步计划，首先要求用户提供正确格式的数据，或者先执行一个数据清洗/转换的子任务来补充缺失的列Y。",
                }
            ]
        }