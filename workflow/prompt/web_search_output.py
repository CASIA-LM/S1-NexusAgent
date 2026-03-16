from pydantic import BaseModel, Field
from typing import List
class WebSearchOutput(BaseModel):
    queries: List[str] = Field(description="The queries to search the web")
