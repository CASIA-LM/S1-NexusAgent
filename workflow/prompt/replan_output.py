from typing import List, Tuple
from pydantic import BaseModel, Field

# --- 基础模型 (Node 和 Plan 保持不变) ---
class Node(BaseModel):
    content: str

class Plan(BaseModel):
    node_id: int = Field(..., description="The id of the node")
    nodes: List[Node] = Field(
        default_factory=list, description="The list of planning steps."
    )
    edges: List[Tuple[int|str, int|str]] = Field(
        default_factory=list, description="The edges of the graph, i.e. the dependencies of the nodes"
    )

# --- 🌟 优化后的 Replan 顶级输出模型 🌟 ---
class ReplanOutput(BaseModel):
    """
    用于 Replan Agent 的结构化输出模型，包含失败分析和新的任务规划。
    这个模型应该与你在 Replan 提示词中定义的 NewPlanOutput Format (Strict JSON) 相匹配。
    """
    thought: str = Field(
        ...,
        description="对执行器失败原因、目标漂移分析和纠正策略的详细分析。这对应于 Replan Prompt 中的 'thought' 字段。"
    )
    new_plan: Plan = Field(
        ...,
        description="包含新的步骤列表 (nodes) 和它们依赖关系 (edges) 的完整规划图。"
    )