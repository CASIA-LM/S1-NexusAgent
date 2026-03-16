from pydantic import BaseModel, Field
from typing import List

class ToolCallOutput(BaseModel):
    args_list: List[dict] = Field(description="The list of key-value dictionaries of the parameters.")
