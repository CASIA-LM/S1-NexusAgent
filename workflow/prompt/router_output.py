from typing import List, Optional, Literal
from enum import Enum
from pydantic import BaseModel, Field

# 保持原有的 Node 定义
# 定义动作枚举
class ActionType(str, Enum):
    FINISH = "finish"
    CALL_EXECUTOR = "call_executor"

# 定义执行所需的参数结构
# class ExecutorParams(BaseModel):
#     subtask: str = Field(..., description="The specific subtask description to be executed right now.")
#     information: str = Field(..., description="Context or necessary information for this subtask.")
#     expected_output: str = Field(..., description="What is expected as the result of this subtask.")

# --- 核心：合并后的 Planner 输出结构 ---
class RouterResponse(BaseModel):
    
    # 2. 路由决策视角
    action: ActionType = Field(
        ..., 
        description="Decision on what to do next. 'finish' if all tasks are done, 'call_executor' to run the next step."
    )
    
    subtask: str = Field(..., description="The specific subtask description to be executed right now.")
    information: str = Field(..., description="Context or necessary information for this subtask.")
    expected_output: str = Field(..., description="What is expected as the result of this subtask.")
    
    reasoning: str = Field(..., description="Brief reasoning behind the plan update and the current action.")
   