from typing import List,Tuple
from enum import Enum
from pydantic import BaseModel, Field

class ActionType(str, Enum):
    FINISH = "finish"
    CALL_EXECUTOR = "call_executor"

class Node(BaseModel):
    # step_id: int = Field(..., description="The id of the step")
    content: str
    #depends_on: List[int] = Field(..., description="The ids of the steps that this step depends on")
    #tool_name: str = Field(..., description="The name of the tool to be used")

class UnknownPlan(BaseModel):
    node_id: int = Field(..., description="The id of the node")
    nodes: List[Node] = Field(
        default_factory=list,
    )
    action: ActionType = Field(
        ..., 
        description="Decision on what to do next. 'finish' if all tasks are done, 'call_executor' to run the next step."
    )
    
    subtask: str = Field(..., description="The specific subtask description to be executed right now.即为分配给executor的子任务，目标为完成用户任务")
    information: str = Field(..., description="Context or necessary information for this subtask.")
    expected_output: str = Field(..., description="What is expected as the result of this subtask.")
    
    reasoning: str = Field(..., description="Brief reasoning behind the plan update and the current action.")