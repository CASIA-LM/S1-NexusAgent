from typing import Dict, Any, List
from pydantic import BaseModel, Field
from langchain_core.tools import StructuredTool
from chemistry_tools.elements._elements import ELEMENTS
from chemistry_tools.pubchem.lookup import get_compounds

from chemistry_tools.pubchem.compound import Compound

from pydantic import BaseModel, Field
from typing import Dict, Any

from workflow.tools.chemistry.utils import is_multiple_smiles, split_smiles,tanimoto,is_smiles, pubchem_query2smiles
from langchain_core.tools import StructuredTool
from workflow.const import Tools
from workflow.utils.minio_utils import upload_content_to_minio

# 1. 元素信息查询 ---------------------------------------------------

class GetElementInformationInput(BaseModel):
    element: str = Field(
        ..., description="元素的化学符号，如 'C'、'H'、'O'、'Fe'"
    )

async def get_element_information_coroutine(element: str) -> Dict[str, Any]:
    """
    查询指定元素的基本信息，包括原子序数、符号、名称、原子量、
    简要描述、电子排布及电子排布字典。
    """
    try:
        ele = ELEMENTS[element]
        return {
            "number": ele.number,
            "symbol": ele.symbol,
            "name": ele.name,
            "mass": ele.mass,
            "description": ele.description,
            "eleconfig": ele.eleconfig,
            "eleconfig_dict": str(ele.eleconfig_dict)
        }
    except Exception as e:
        return {"error": f"元素信息查询失败: {str(e)}"}

get_element_information_tool = StructuredTool.from_function(
    coroutine=get_element_information_coroutine,
    name=Tools.GET_ELEMENT_INFORMATION,
    description="""
    【领域：化学】
    查询指定化学元素的详细信息。
    返回内容包括：
      - 原子序数 (number)
      - 元素符号 (symbol)
      - 元素名称 (name)
      - 原子量 (mass)
      - 元素简介 (description)
      - 电子排布 (eleconfig)
      - 电子排布字典 (eleconfig_dict)
    """,
    args_schema=GetElementInformationInput,
    metadata={"args_schema_json": GetElementInformationInput.schema()}
)


# 2. 获取化合物CID ---------------------------------------------------

class GetCompoundCIDInput(BaseModel):
    compound: str = Field(
        ..., description="化合物的名称字符串，例如 'water'、'sodium chloride'、'glucose'"
    )

async def get_compound_CID_coroutine(compound: str) -> Dict[str, Any]:
    """
    使用 PubChem 数据库，根据化合物名称检索对应的 CID (Compound Identifier)。
    """
    try:
        CID = get_compounds(compound)[0].cid
        return {"compound_CID": CID}
    except Exception as e:
        return {"error": f"获取化合物CID失败: {str(e)}"}

get_compound_CID_tool = StructuredTool.from_function(
    coroutine=get_compound_CID_coroutine,
    name=Tools.GET_COMPOUND_CID,
    description="""
    【领域：化学】
    根据给定的化合物名称，查询其在 PubChem 数据库中的 CID (Compound Identifier)。
    返回：
      - compound_CID: 该化合物的 PubChem CID
    """,
    args_schema=GetCompoundCIDInput,
    metadata={"args_schema_json": GetCompoundCIDInput.schema()}
)


# 3. CID 转分子式 ---------------------------------------------------

class ConvertCIDToFormulaInput(BaseModel):
    compound_CID: int = Field(
        ..., description="PubChem 化合物 CID，例如 962（水）、5234（食盐）、5988（葡萄糖）"
    )

async def convert_compound_CID_to_formula_coroutine(compound_CID: int) -> Dict[str, Any]:
    """
    根据给定的 PubChem CID，获取对应化合物的分子式。
    """
    try:
        compound = Compound.from_cid(compound_CID)
        return {"molecular_formula": compound.molecular_formula}
    except Exception as e:
        return {"error": f"CID 转分子式失败: {str(e)}"}

convert_compound_CID_to_formula_tool = StructuredTool.from_function(
    coroutine=convert_compound_CID_to_formula_coroutine,
    name=Tools.CONVERT_CID_TO_FORMULA,
    description="""
    【领域：化学】
    根据 PubChem 化合物 CID，获取该化合物的分子式。
    返回：
      - molecular_formula: 分子式字符串，例如 H2O、NaCl、C6H12O6
    """,
    args_schema=ConvertCIDToFormulaInput,
    metadata={"args_schema_json": ConvertCIDToFormulaInput.schema()}
)



# 5. CID 获取化合物电荷 ---------------------------------------------------

class GetCompoundChargeByCIDInput(BaseModel):
    compound_CID: int = Field(
        ..., description="PubChem 化合物 CID，例如 962（水）、5234（食盐）、70678590（有机离子）"
    )

async def get_compound_charge_by_CID_coroutine(compound_CID: int) -> Dict[str, Any]:
    """
    根据 PubChem CID 获取化合物的电荷。
    """
    try:
        compound = Compound.from_cid(compound_CID)
        return {"charge": compound.charge}
    except Exception as e:
        return {"error": f"CID 获取电荷失败: {str(e)}"}

get_compound_charge_by_CID_tool = StructuredTool.from_function(
    coroutine=get_compound_charge_by_CID_coroutine,
    name=Tools.GET_COMPOUND_CHARGE_BY_CID,
    description="""
    【领域：化学】
    根据 PubChem 化合物 CID，获取该化合物的电荷。
    返回：
      - charge: 整数，化合物的净电荷
    """,
    args_schema=GetCompoundChargeByCIDInput,
    metadata={"args_schema_json": GetCompoundChargeByCIDInput.schema()}
)


# 6. CID 转 IUPAC 名称 ---------------------------------------------------

class ConvertCIDToIUPACInput(BaseModel):
    compound_CID: int = Field(
        ..., description="PubChem 化合物 CID，例如 962（水）、5234（食盐）、5988（葡萄糖）"
    )

async def convert_compound_CID_to_IUPAC_coroutine(compound_CID: int) -> Dict[str, Any]:
    """
    根据 PubChem CID 获取化合物的 IUPAC 系统命名。
    """
    try:
        compound = Compound.from_cid(compound_CID)
        return {"iupac_name": compound.iupac_name}
    except Exception as e:
        return {"error": f"CID 转 IUPAC 名称失败: {str(e)}"}

convert_compound_CID_to_IUPAC_tool = StructuredTool.from_function(
    coroutine=convert_compound_CID_to_IUPAC_coroutine,
    name=Tools.CONVERT_CID_TO_IUPAC,
    description="""
    【领域：化学】
    根据 PubChem 化合物 CID，获取该化合物的 IUPAC 名称。
    返回：
      - iupac_name: IUPAC 标准命名
    """,
    args_schema=ConvertCIDToIUPACInput,
    metadata={"args_schema_json": ConvertCIDToIUPACInput.schema()}
)


# 7. 光谱相似度计算 ---------------------------------------------------

class CalculateSpectrumSimilarityInput(BaseModel):
    mz_top: List[float] = Field(..., description="上方光谱的 m/z 数组")
    intensities_top: List[float] = Field(..., description="上方光谱对应的强度数组")
    mz_bottom: List[float] = Field(..., description="下方光谱的 m/z 数组")
    intensities_bottom: List[float] = Field(..., description="下方光谱对应的强度数组")

async def calculate_spectrum_similarity_coroutine(
    mz_top: List[float],
    intensities_top: List[float],
    mz_bottom: List[float],
    intensities_bottom: List[float]
) -> Dict[str, Any]:
    """
    计算两个质谱之间的相似度分数。
    """
    try:
        top_spec = create_array(mz=mz_top, intensities=intensities_top)
        bottom_spec = create_array(mz=mz_bottom, intensities=intensities_bottom)
        spec_sim = SpectrumSimilarity(top_spec, bottom_spec)
        score_1, score_2 = spec_sim.score()
        return {
            "similarity_score_top_to_bottom": float(score_1),
            "similarity_score_bottom_to_top": float(score_2)
        }
    except Exception as e:
        return {"error": f"光谱相似度计算失败: {str(e)}"}

calculate_spectrum_similarity_tool = StructuredTool.from_function(
    coroutine=calculate_spectrum_similarity_coroutine,
    name=Tools.CALCULATE_SPECTRUM_SIMILARITY,
    description="""
    【领域：化学】
    计算两个质谱的相似度分数。
    返回：
      - similarity_score_top_to_bottom: 光谱A相对于光谱B的相似度
      - similarity_score_bottom_to_top: 光谱B相对于光谱A的相似度
    """,
    args_schema=CalculateSpectrumSimilarityInput,
    metadata={"args_schema_json": CalculateSpectrumSimilarityInput.schema()}
)

