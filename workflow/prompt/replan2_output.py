from pydantic import BaseModel, Field
from typing import List, Literal, Optional
from workflow.prompt import planner_output


PlanNode = planner_output.Node
# 定义 Replan 的输出结构
class ReplanDecision(BaseModel):
    thought: str = Field(description="思考过程：分析上一步执行结果是否符合预期，以及是否需要调整后续计划。")
    decision: Literal["continue", "update_plan", "finish"] = Field(
        description="决策动作：'continue'表示按原计划继续；'update_plan'表示修改后续步骤；'finish'表示任务已完成。"
    )
    new_steps: Optional[List[PlanNode]] = Field(
        default=None, 
        description="如果 decision 是 'update_plan'，则必须提供从当前位置开始的新的后续步骤列表。"
    )
    reason: str = Field(description="做出该决策的原因摘要。")