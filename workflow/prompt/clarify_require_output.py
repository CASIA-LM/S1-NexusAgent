from pydantic import BaseModel, Field

class RequireResult(BaseModel):
    missing_args: list[str] = Field(description="缺失参数列表")
    missing_guide: str = Field(description="引导信息")