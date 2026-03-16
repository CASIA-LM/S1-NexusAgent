from pydantic import BaseModel, Field

class IdentifyLanguage(BaseModel):
    locale: str = Field(description="The user's detected language locale (e.g., en-US, zh-CN).")