from typing import List,Tuple
from enum import Enum
from pydantic import BaseModel, Field

class Node(BaseModel):
    # step_id: int = Field(..., description="The id of the step")
    content: str
    #depends_on: List[int] = Field(..., description="The ids of the steps that this step depends on")
    #tool_name: str = Field(..., description="The name of the tool to be used")

class PrePlan(BaseModel):
    node_id: int = Field(..., description="The id of the node")
    nodes: List[Node] = Field(
        default_factory=list,
    )
   