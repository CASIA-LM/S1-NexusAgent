from pydantic import BaseModel, Field
from typing import List

class SummaryOutput(BaseModel):
    """用于存储和格式化缺失专业工具的总结和用户提示。"""
    
    # 对应您原有的 `tools_note`，现在侧重于缺失的“功能”描述
    user_guidance_tip: str = Field(
        ...,
        description=(
            "一个精炼、用户友好的中文提示（不超过50字），**总结所有缺失专业工具的核心功能需求**，"
            "例如：'报告缺少分子结构可视化与三维建模功能'，让用户明确缺少的具体能力。"
        )
    )
    
    # 一个去重合并后的缺失工具列表，存储工具名称
    consolidated_tools_list: List[str] = Field(
        ...,
        description="从原始工具列表中提取并去重后的专业工具名称列表，例如 ['SolidWorks', 'ABAQUS', 'Gaussian']。"
    )
    