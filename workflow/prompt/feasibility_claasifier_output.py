from pydantic import BaseModel, Field
from typing import Literal

class ToolFeasibility(BaseModel):
    """用于评估一个科学工具需求的可行性，并将其分类为代码实现或专业软件。"""
    
    feasibility: Literal["code_agent", "professional_software"] = Field(
        ...,
        description=(
            "分类决策。\n"
            "'code_agent'：任务可以通过编写代码并利用常用的、开源的库（如 Python 的 matplotlib, pandas, numpy, scikit-learn, RDKit, Biopython 等）来解决。\n"
            "'professional_software'：任务需要专有的、商业的、或复杂的非编码工具（如 Gaussian, VASP, ANSYS, COMSOL, AutoCAD, 实验室设备操作软件等）才能完成。"
        )
    )
    