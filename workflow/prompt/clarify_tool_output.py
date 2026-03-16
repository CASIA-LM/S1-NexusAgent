from pydantic import BaseModel, Field


class ToolResult(BaseModel):
    tool_name: str = Field(description="最适合的工具")
