from pydantic import BaseModel,Field


class Result(BaseModel):
    clarification_completed : bool = Field(description="the clarification been completed")
    message: str = Field(description="the clarification message")

    class Config:
        json_schema_extra = {
            "examples": [
                {
                    'clarification_completed': True,
                    'message': 'the clarification has been completed',
                },
                {
                    'clarification_completed': False,
                    'message': 'May I ask what amino acid sequence you would like to predict? For example: TSLRILNNGHAFNVEFDDSQD',
                }
            ]
        }