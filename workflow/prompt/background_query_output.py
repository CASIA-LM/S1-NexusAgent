from pydantic import BaseModel
from typing import List
from pydantic import Field

class BackgroundQueryOutput(BaseModel):
    proper_noun_queries: List[str] = Field(description="A list of queries for proper nouns.")
    tool_queries: List[str] = Field(description="A list of queries for tools.")
