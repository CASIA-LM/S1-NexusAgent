from pydantic import BaseModel


class Result(BaseModel):
    small_talk: int

    class Config:
        json_schema_extra = {
            "examples": [
                {
                    'small_talk': 1
                },
                {
                    'small_talk': 0
                }
            ]
        }
