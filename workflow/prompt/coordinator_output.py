from pydantic import BaseModel

class Result(BaseModel):
    query_scene: str
    matching : bool

    class Config:
        json_schema_extra = {
            "examples": [
                {
                    'query_scene':'小核酸',
                    'matching':True
                },
                {
                    'query_scene': '数字细胞',
                    'matching': True
                },
                {
                    'query_scene': '',
                    'matching': False
                },
            ]
        }
