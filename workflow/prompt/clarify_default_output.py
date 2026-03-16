from pydantic import BaseModel, Field

class DefaultResult(BaseModel):
    default_guide: str = Field(description="引导信息")
    need_guide: bool