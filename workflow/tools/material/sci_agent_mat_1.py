
from typing import Dict, Any
import logging
import asyncio
from pymatgen.ext.matproj import MPRester
from pydantic import BaseModel, Field

from workflow.tools.chemistry.utils import is_multiple_smiles, split_smiles,tanimoto,is_smiles, pubchem_query2smiles
from langchain_core.tools import StructuredTool
from workflow.const import Tools

from workflow.utils.minio_utils import upload_content_to_minio
import aiohttp

# 假设已有全局 api_key
import os as _os_mat
api_key = _os_mat.environ.get("MP_API_KEY", "")

# ============================================================
# 1. 按元素检索材料
# ============================================================
class SearchMaterialsContainingElementsInput(BaseModel):
    element: str = Field(
        ...,
        description="指定要包含的元素字符串，用 '.' 分隔多个元素。例如 'Si.O' 表示包含 Si 和 O 的材料"
    )

async def search_materials_containing_elements_coroutine(
    element: str
) -> Dict[str, Any]:
    """
    查询包含指定元素的材料，返回不超过50条结果。
    """
    try:
        mpr = MPRester(api_key)
        element = element.replace("\"","").replace("\'","")
        elements_list = element.split(".")

        docs = mpr.materials.summary.search(
            elements=elements_list,
            # fields=["material_id", "band_gap", "volume"]
        )

        markdown = f"## Results for materials containing {elements_list}: ##\n"
        if not docs:
            markdown += "No materials found"
        else:
            for i, doc in enumerate(docs):
                # 提取所需字段
                material_id = doc.get("material_id", "Unknown ID")
                band_gap = doc.get("band_gap", "N/A")
                volume = doc.get("volume", "N/A")

                markdown += (
                    f"- Material ID: {material_id}\t"
                    f"Band Gap: {band_gap}\t"
                    f"Volume: {volume}\n"
                )
                # markdown += f"- Material ID: {doc.material_id}\tBand Gap: {doc.band_gap}\tVolume: {doc.volume}\n"
                if i == 49:  # 限制 50 条
                    break
        return {"results": markdown}

    except Exception as e:
        logging.error(f"Error in search_materials_containing_elements: {e}")
        return {"error": str(e)}

search_materials_containing_elements_tool = StructuredTool.from_function(
    coroutine=search_materials_containing_elements_coroutine,
    name=Tools.search_materials_containing_elements,
    description="""
    【领域：材料科学】
    按元素组合检索材料信息（最多返回50条）。
    输入用 '.' 分隔多个元素，例如 'Si.O' 表示查询所有同时包含 Si 和 O 的材料。
    输出包含材料ID、带隙和体积。
    """,
    args_schema=SearchMaterialsContainingElementsInput,
    metadata={"args_schema_json": SearchMaterialsContainingElementsInput.schema()}
)

# ============================================================
# 2. 按化学体系检索材料
# ============================================================
class SearchMaterialsByChemsysInput(BaseModel):
    chemsys: str = Field(
        ..., description="化学体系字符串，用 '-' 分隔元素，例如 'Si-O'"
    )

async def search_materials_by_chemsys_coroutine(
    chemsys: str
) -> Dict[str, Any]:
    """
    查询指定化学体系的材料。
    """
    try:
        mpr = MPRester(api_key)
        chemsys = chemsys.replace("\"","").replace("\'","")

        docs = mpr.materials.summary.search(
            chemsys=chemsys,
            # fields=["material_id", "band_gap", "volume"]
        )

        markdown = f"## Results for chemsys {chemsys}: ##\n"
        if not docs:
            markdown += "No materials found"
        else:
            for doc in docs:
                # 提取需要的字段
                material_id = doc.get("material_id", "Unknown ID")
                band_gap = doc.get("band_gap", "N/A")
                volume = doc.get("volume", "N/A")

                markdown += (
                    f"- Material ID: {material_id}\t"
                    f"Band Gap: {band_gap}\t"
                    f"Volume: {volume}\n"
                )
                # markdown += f"- Material ID: {doc.material_id}\tBand Gap: {doc.band_gap}\tVolume: {doc.volume}\n"

        return {"results": markdown}

    except Exception as e:
        logging.error(f"Error in search_materials_by_chemsys: {e}")
        return {"error": str(e)}

search_materials_by_chemsys_tool = StructuredTool.from_function(
    coroutine=search_materials_by_chemsys_coroutine,
    name=Tools.search_materials_by_chemsys,
    description="""
    【领域：材料科学】
    按化学体系检索材料信息。
    输入为化学体系字符串，例如 'Si-O'。
    输出包含材料ID、带隙和体积。
    """,
    args_schema=SearchMaterialsByChemsysInput,
    metadata={"args_schema_json": SearchMaterialsByChemsysInput.schema()}
)

# ============================================================
# 3. 根据化学式获取材料 ID
# ============================================================
class GetMaterialIdByFormulaInput(BaseModel):
    formula: str = Field(
        ..., description="材料的化学式，例如 'Fe2O3' 或 'LiFePO4'"
    )

async def get_material_id_by_formula_coroutine(
    formula: str
) -> Dict[str, Any]:
    """
    根据化学式获取材料ID。
    """
    try:
        mpr = MPRester(api_key)
        cleaned_formula = formula.replace(" ", "").replace("\n", "").replace("\'", "").replace("\"", "")
        if "=" in cleaned_formula:
            _, id = cleaned_formula.split("=")
        else:
            id = cleaned_formula

        docs = mpr.materials.summary.search(
            formula=[id],
            # fields=["material_id"]
        )

        markdown = f"## Input Formula: {id}\n## Material ID: "
        if not docs:
            markdown += "No materials found"
        else:
            for doc in docs:
                material_id = doc.get("material_id", "Unknown ID")  ###
                markdown += f"{material_id}\n"  ###
                # markdown += f"{doc.material_id}\n"

        return {"results": markdown}

    except Exception as e:
        logging.error(f"Error in get_material_id_by_formula: {e}")
        return {"error": str(e)}

get_material_id_by_formula_tool = StructuredTool.from_function(
    coroutine=get_material_id_by_formula_coroutine,
    name=Tools.get_material_id_by_formula,
    description="""
    【领域：材料科学】
    根据化学式检索材料ID。
    输入为化学式，例如 'Fe2O3'。
    输出为对应的材料ID。
    """,
    args_schema=GetMaterialIdByFormulaInput,
    metadata={"args_schema_json": GetMaterialIdByFormulaInput.schema()}
)

# ============================================================
# 4. 根据材料 ID 获取化学式
# ============================================================
class GetFormulaByMaterialIdInput(BaseModel):
    material_id: str = Field(
        ..., description="材料ID，多个ID用 '.' 分隔，例如 'mp-1.mp-555322'"
    )

async def get_formula_by_material_id_coroutine(
    material_id: str
) -> Dict[str, Any]:
    """
    根据材料ID获取化学式。
    """
    try:
        cleaned_id = material_id.replace(" ", "").replace("\n", "").replace("\'", "").replace("\"", "")
        if "=" in cleaned_id:
            _, id = cleaned_id.split("=")
        else:
            id = cleaned_id

        id_list = id.split(".")

        mpr = MPRester(api_key)
        docs = mpr.materials.summary.search(
            material_ids=id_list,
            # fields=["material_id", "formula_pretty"]
        )

        markdown = f"## Input Material IDs: {id_list}\n## Formula Results:\n"
        if not docs:
            markdown += "No materials found"
        else:
            for doc in docs:
                material_id = doc.get("material_id", "Unknown ID")
                formula_pretty = doc.get("formula_pretty", "Unknown Formula")

                # 构建 Markdown 输出
                markdown += (
                    f"- Material ID: {material_id}\t"
                    f"Formula: {formula_pretty}\t"
                )
                # markdown += f"- Material ID: {doc.material_id}\tFormula: {doc.formula_pretty}\n"

        return {"results": markdown}

    except Exception as e:
        logging.error(f"Error in get_formula_by_material_id: {e}")
        return {"error": str(e)}

get_formula_by_material_id_tool = StructuredTool.from_function(
    coroutine=get_formula_by_material_id_coroutine,
    name=Tools.get_formula_by_material_id,
    description="""
    【领域：材料科学】
    根据材料ID获取化学式。
    输入为一个或多个材料ID，多个用 '.' 分隔，例如 'mp-1.mp-555322'。
    输出为对应的化学式。
    """,
    args_schema=GetFormulaByMaterialIdInput,
    metadata={"args_schema_json": GetFormulaByMaterialIdInput.schema()}
)






class GetBandGapByMaterialIDInput(BaseModel):
    material_id: str = Field(
        ..., description="材料的 material_id。如果要查询多个材料，请使用 '.' 分隔，例如 'mp-1.mp-555322'"
    )

async def get_band_gap_by_material_id_coroutine(material_id: str) -> Dict[str, Any]:
    """
    根据材料的 material_id 获取其带隙信息。
    支持单个或多个 material_id 输入，返回带隙结果 Markdown。
    """
    try:
        cleaned_id = material_id.strip().replace("'", "").replace('"', "")
        if "=" in cleaned_id:
            _, id_val = cleaned_id.split("=")
        else:
            id_val = cleaned_id

        id_list = id_val.split(".")  # 支持多个 material_id
        mpr = MPRester(api_key)
        docs = mpr.materials.summary.search(
            material_ids=id_list,
            # fields=["material_id", "band_gap"]
        )

        markdown = "## Get Band Gap by Material ID\n### Results\n"
        if not docs:
            markdown += "No materials found"
        else:
            for doc in docs:
                material_id = doc.get("material_id", "Unknown ID")
                band_gap = doc.get("band_gap", "N/A")

                # 构建 Markdown 输出
                markdown += (
                    f"- Material ID: {material_id}\t"
                    f"Band Gap: {band_gap} eV\n"
                )
                # markdown += f"**Material ID:** {doc.material_id}\t"
                # markdown += f"**Band Gap:** {doc.band_gap} eV\n"

        return {"markdown": markdown}

    except Exception as e:
        return {"error": f"获取材料带隙失败: {str(e)}"}


get_band_gap_by_material_id_tool = StructuredTool.from_function(
    coroutine=get_band_gap_by_material_id_coroutine,
    name=Tools.get_band_gap_by_material_id,
    description="""
    【领域：材料科学】
    根据材料的 material_id 获取其带隙 (band gap)。
    - 支持单个或多个 material_id 输入，多个 ID 用 '.' 分隔，例如 "mp-1.mp-555322"。
    - 返回 Markdown 格式，包含材料 ID 及其对应的带隙 (单位 eV)。
    """,
    args_schema=GetBandGapByMaterialIDInput,
    metadata={"args_schema_json": GetBandGapByMaterialIDInput.schema()}
)

class GetBandGapByFormulaInput(BaseModel):
    formula: str = Field(
        ..., description="材料化学式。如果要查询多个，请使用 '.' 分隔，例如 'Al2O3.SiO2'"
    )

async def get_band_gap_by_formula_coroutine(formula: str) -> Dict[str, Any]:
    """
    根据材料化学式获取带隙信息。
    支持单个或多个 formula 输入，返回带隙结果 Markdown。
    """
    try:
        cleaned_formula = formula.strip().replace("'", "").replace('"', "")
        formula_list = cleaned_formula.split(".")

        mpr = MPRester(api_key)
        docs = mpr.materials.summary.search(formula=formula_list)

        markdown = "## Get Band Gap by Formula\n### Results\n"
        if not docs:
            markdown += "No materials found"
        else:
            # for doc in docs:
            #     markdown += f"**Formula:** {doc.composition_reduced}\t"  ## formula_pretty
            #     markdown += f"**Band Gap:** {doc.band_gap} eV\n" 
            for doc in docs:
                composition_reduced = doc.get("composition_reduced", "N/A")  # 确保字段存在
                band_gap = doc.get("band_gap", "N/A")      # 确保字段存在
                markdown += f"**Formula:** {composition_reduced}\t"
                markdown += f"**Band Gap:** {band_gap} eV\n"

        return {"markdown": markdown}

    except Exception as e:
        return {"error": f"获取材料带隙失败: {str(e)}"}


get_band_gap_by_formula_tool = StructuredTool.from_function(
    coroutine=get_band_gap_by_formula_coroutine,
    name=Tools.get_band_gap_by_formula,
    description="""
    【领域：材料科学】
    根据材料的化学式 (formula) 获取其带隙 (band gap)。
    - 支持单个或多个 formula 输入，多个化学式用 '.' 分隔，例如 "Al2O3.SiO2"。
    - 返回 Markdown 格式，包含材料化学式及其对应的带隙 (单位 eV)。
    """,
    args_schema=GetBandGapByFormulaInput,
    metadata={"args_schema_json": GetBandGapByFormulaInput.schema()}
)
