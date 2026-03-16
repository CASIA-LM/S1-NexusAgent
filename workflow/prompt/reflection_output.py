from pydantic import BaseModel, Field
from typing import Optional

class Result(BaseModel):
    # 细分维度评分，强制模型进行多维度思考
    completeness_score: int = Field(..., description="完整性评分(0-10): 是否涵盖了计划中的所有关键步骤？是否有遗漏的数据？")
    accuracy_score: int = Field(..., description="准确性评分(0-10): 工具返回的数据是否有效？是否存在幻觉或明显的错误？")
    logic_score: int = Field(..., description="逻辑性评分(0-10): 执行步骤之间是否存在因果断裂？推理是否严密？")
    alignment_score: int = Field(..., description="相关性评分(0-10): 结果是否直接回应了用户的核心科学问题？")
    
    # 最终综合评分
    score: int = Field(..., description="加权后的最终综合评分 (0-100)。通常基于上述维度的加权总和。")
    
    # 评价与建议
    thought: str = Field(..., description="专业的评审意见。不仅要指出问题，还要说明‘为什么’当前结果不足以支撑科学结论。")
    suggestion: Optional[str] = Field(None, description="针对Planner的具体的改进指令。如果分数较低，必须填写此字段告诉Planner下一步查什么。")

    class Config:
        json_schema_extra = {
            "examples": [
                {
                    "completeness_score": 8,
                    "accuracy_score": 9,
                    "logic_score": 8,
                    "alignment_score": 9,
                    "score": 85,
                    "thought": "核心数据已通过工具获取，文献引用准确。虽然部分边缘数据缺失，但不影响核心结论的推导。建议直接生成报告。",
                    "suggestion": None
                },
                {
                    "completeness_score": 4,
                    "accuracy_score": 5,
                    "logic_score": 6,
                    "alignment_score": 8,
                    "score": 55,
                    "thought": "虽然理解了用户意图，但关键的实验数据（如XX参数）在工具调用中返回为空，导致无法进行下一步论证。目前的结论缺乏实证支持。",
                    "suggestion": "请重新规划搜索路径，尝试使用更广泛的关键词查找XX参数，或查找替代性的同类数据。"
                }
            ]
        }