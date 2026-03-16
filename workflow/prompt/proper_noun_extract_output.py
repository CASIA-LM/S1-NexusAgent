from pydantic import BaseModel
from typing import List
from pydantic import Field

class ProperNounExtractOutput(BaseModel):
    proper_nouns: List[str] = Field(description="The proper nouns in the user's question")
