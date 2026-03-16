from pydantic import BaseModel, Field
from typing import List



# class ToolInfoExtractOutput(BaseModel):
#     tools: List[str]=Field(description="The names of the tools")


#     class Config:
#         json_schema_extra = {
#             "examples": [
#                 {
            
#                     "tools": "彩云天气",
                    
#                 }

#             ]
#         }
# 1. 定义单个工具的结构
class ToolInfo(BaseModel):
    name: str = Field(..., description="工具的名称。")
    description: str = Field(..., description="关于工具功能的一句话简明描述。")

# 2. 定义整个模型输出的顶层结构
class ToolInfoExtractOutput(BaseModel):
    # 'tools' 属性是一个列表，列表中的每个元素都必须符合上面 ToolInfo 的结构
    tools: List[ToolInfo] = Field(..., description="一个包含推荐工具及其描述的列表。")

# 3. 定义需要新工具的时候创建的工具描述  
class NeedToolInfo(BaseModel):
    tool_name: str = Field(description="The name of the tool")
    tool_purpose: str = Field(description="The purpose of the tool")
    tool_technique_requirement: str = Field(description="The technique requirement of the tool")

    class Config:
        json_schema_extra = {
            "examples": [
                {
                    "tool_name": "molecule_3d_visualizer",
                    "tool_purpose": "Create interactive 3D molecular structure visualizations for small molecules like H2O, CH4, etc. Generate proper atomic coordinates, bond angles, and interactive HTML visualizations with rotation and zoom capabilities.",
                    "tool_technique_requirement": "Use matplotlib and mplot3d for 3D plotting. Include atomic coordinates generation based on molecular geometry, proper bond lengths and angles for common molecules, color-coded atoms (O=red, H=white), interactive controls, and save as both HTML and PNG formats."
                },
                {
                    "tool_name": "quantum_circuit_simulator",
                    "tool_purpose": "Simulate and visualize quantum computing circuits with common gates (CNOT, Hadamard, Pauli-X/Y/Z). Provide statevector evolution, measurement probabilities, and circuit diagram generation.",
                    "tool_technique_requirement": "Use qiskit or cirq for quantum simulation. Implement gate operations, statevector calculation, probability distribution visualization with matplotlib, interactive circuit diagram rendering with SVG/HTML, and support for up to 5 qubit systems."
                },
                {
                    "tool_name": "crystal_structure_analyzer",
                    "tool_purpose": "Generate and analyze crystal structures for common materials (Si, NaCl, graphene) with proper lattice parameters, atomic positions, and symmetry operations.",
                    "tool_technique_requirement": "Use pymatgen or ase for crystal structure generation. Implement Bravais lattice construction, space group symmetry, atomic coordinate calculation, 3D visualization with VESTA-like features, and export to CIF/XYZ formats with interactive HTML visualization."
                }
            ]
        }