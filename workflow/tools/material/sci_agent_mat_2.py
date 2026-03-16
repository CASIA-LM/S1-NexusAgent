from pydantic import BaseModel, Field
from typing import Dict, Any
import logging
import asyncio

from workflow.tools.chemistry.utils import is_multiple_smiles, split_smiles,tanimoto,is_smiles, pubchem_query2smiles
from langchain_core.tools import StructuredTool
from workflow.const import Tools

from workflow.utils.minio_utils import upload_content_to_minio
import aiohttp

# 假设已有全局 api_key
import os as _os_mat
api_key = _os_mat.environ.get("MP_API_KEY", "")
from pymatgen.ext.matproj import MPRester
#from mp_api.client import MPRester
from io import BytesIO
from datetime import datetime
import pickle


# ---------------------------
# 1. Get Density by Material ID
# ---------------------------
class GetDensityByMaterialIdInput(BaseModel):
    material_id: str = Field(
        ..., description="材料的 Material ID，例如 'mp-1'；如果输入多个，用 '.' 分隔，如 'mp-1.mp-555322'"
    )

async def get_density_by_material_id_coroutine(material_id: str) -> Dict[str, str]:
    try:
        cleaned_id = material_id.replace(" ", "").replace("\n", "").replace("\'", "").replace("\"", "")
        mid = cleaned_id.split("=")[1] if "=" in cleaned_id else cleaned_id
        id_list = [mid]

        mpr = MPRester(api_key)
        docs = mpr.materials.summary.search(material_ids=id_list)

        markdown = "## Get density by material id\n## Results\n"
        if not docs:
            markdown += "No materials found"
        else:
            for doc in docs:
                markdown += f"**Input material id:** {doc.material_id}\t\t**Density:** {doc.density} g/cm³\n"

        return {"result": markdown}
    except Exception as e:
        logging.error(f"Error in get_density_by_material_id: {e}")
        return {"error": str(e)}

get_density_by_material_id_tool = StructuredTool.from_function(
    coroutine=get_density_by_material_id_coroutine,
    name=Tools.GET_DENSITY_BY_MATERIAL_ID,
    description="根据 Material ID 查询材料密度信息，返回 Markdown 格式结果，包括输入 ID 与密度 (g/cm³)。",
    args_schema=GetDensityByMaterialIdInput,
    metadata={"args_schema_json": GetDensityByMaterialIdInput.schema()}
)


# ---------------------------
# 3. Get Volume by Material ID
# ---------------------------
class GetVolumeByMaterialIdInput(BaseModel):
    material_id: str = Field(..., description="材料 Material ID，例如 'mp-1'，仅支持单个 ID 输入")

async def get_volume_by_material_id_coroutine(material_id: str) -> Dict[str, str]:
    try:
        cleaned_id = material_id.replace(" ", "").replace("\n", "").replace("\'", "").replace("\"", "")
        mid = cleaned_id.split("=")[1] if "=" in cleaned_id else cleaned_id
        id_list = [mid]

        mpr = MPRester(api_key)
        docs = mpr.materials.summary.search(material_ids=id_list)

        markdown = "## Get Volume by material id\n## Results\n"
        if not docs:
            markdown += "No materials found"
        else:
            for doc in docs:
                markdown += f"**Input material id:** {doc.material_id}\t\t**Volume:** {doc.volume} Å³\n"

        return {"result": markdown}
    except Exception as e:
        logging.error(f"Error in get_volume_by_material_id: {e}")
        return {"error": str(e)}

get_volume_by_material_id_tool = StructuredTool.from_function(
    coroutine=get_volume_by_material_id_coroutine,
    name=Tools.GET_VOLUME_BY_MATERIAL_ID,
    description="根据 Material ID 查询材料体积信息，返回 Markdown 格式结果，包括输入 ID 与体积 (Å³)。",
    args_schema=GetVolumeByMaterialIdInput,
    metadata={"args_schema_json": GetVolumeByMaterialIdInput.schema()}
)


# ---------------------------
# 4. Get Volume by Formula
# ---------------------------
class GetVolumeByFormulaInput(BaseModel):
    formula: str = Field(..., description="材料化学式，例如 'Al2O3'；多个化学式用 '.' 分隔，如 'Al2O3.SiO2'")

async def get_volume_by_formula_coroutine(formula: str) -> Dict[str, str]:
    try:
        cleaned_formula = formula.replace(" ", "").replace("\n", "").replace("\'", "").replace("\"", "")
        formula_list = cleaned_formula.split(".")
        mpr = MPRester(api_key)
        docs = mpr.materials.summary.search(formula=formula_list)

        markdown = "## Get Volume by formula\n## Results\n"
        if not docs:
            markdown += "No materials found"
        else:
            for doc in docs:
                markdown += f"**Input formula:** {doc.composition_reduced}\t\t**Volume:** {doc.volume} Å³\n"

        return {"result": markdown}
    except Exception as e:
        return {"error": f"Error in get_volume_by_formula: {str(e)}"}

get_volume_by_formula_tool = StructuredTool.from_function(
    coroutine=get_volume_by_formula_coroutine,
    name=Tools.GET_VOLUME_BY_FORMULA,
    description="根据化学式查询材料体积信息，返回 Markdown 格式结果，包括输入化学式与体积 (Å³)。",
    args_schema=GetVolumeByFormulaInput,
    metadata={"args_schema_json": GetVolumeByFormulaInput.schema()}
)





# ========================== 工具1: Energy above hull ==========================
class GetEnergyAboveHullInput(BaseModel):
    material_id: str = Field(
        ..., description="材料 ID，可输入多个，用 '.' 分隔，例如 'mp-1.mp-555322'"
    )

async def get_energy_above_hull_coroutine(material_id: str) -> Dict[str, Any]:
    """
    根据材料 ID 获取材料的能量高于凸包 (energy above hull)，返回 Markdown 格式结果。
    """
    try:
        cleaned_id = material_id.replace(" ", "").replace("\n", "").replace("'", "").replace('"', "")
        mpr = MPRester(api_key)
        id_list = cleaned_id.split(".")
        docs = mpr.materials.summary.search(material_ids=id_list)
        markdown = "## Get results for materials:\n## Results:\n"
        if not docs:
            markdown += "No materials found"
        else:
            for doc in docs:
                markdown += f"**Input material id:** {doc.material_id}\t**Energy above hull:** {doc.energy_above_hull} eV/atom\n"
        return {"result": markdown}
    except Exception as e:
        logging.error(f"Error in get_energy_above_hull_coroutine: {e}")
        return {"error": str(e)}

get_energy_above_hull_tool = StructuredTool.from_function(
    coroutine=get_energy_above_hull_coroutine,
    name=Tools.GET_ENERGY_ABOVE_HULL,
    description="""
    【领域：材料科学】
    根据材料 ID 获取材料的能量高于凸包 (energy above hull)。
    返回 Markdown 格式结果，支持多个材料 ID 输入，用 '.' 分隔。
    """,
    args_schema=GetEnergyAboveHullInput,
    metadata={"args_schema_json": GetEnergyAboveHullInput.schema()}
)

# ========================== 工具2: Formation energy per atom ==========================
class GetFormationEnergyPerAtomInput(BaseModel):
    material_id: str = Field(
        ..., description="材料 ID，可输入多个，用 '.' 分隔，例如 'mp-1.mp-555322'"
    )

async def get_formation_energy_per_atom_coroutine(material_id: str) -> Dict[str, Any]:
    """
    根据材料 ID 获取材料的形成能 per atom (formation energy per atom)，返回 Markdown 格式结果。
    """
    try:
        cleaned_id = material_id.replace(" ", "").replace("\n", "")
        mpr = MPRester(api_key)
        id_list = cleaned_id.split(".")
        docs = mpr.materials.summary.search(material_ids=id_list)
        markdown = "## Get the formation energy per atom of materials:\n## Results:\n"
        if not docs:
            markdown += "No materials found"
        else:
            for doc in docs:
                markdown += f"**Input material id:** {doc.material_id}\n**Formation energy per atom:** {doc.formation_energy_per_atom} eV/atom\n"
        return {"result": markdown}
    except Exception as e:
        logging.error(f"Error in get_formation_energy_per_atom_coroutine: {e}")
        return {"error": str(e)}

get_formation_energy_per_atom_tool = StructuredTool.from_function(
    coroutine=get_formation_energy_per_atom_coroutine,
    name=Tools.GET_FORMATION_ENERGY_PER_ATOM,
    description="""
    【领域：材料科学】
    根据材料 ID 获取材料的形成能 per atom (formation energy per atom)。
    返回 Markdown 格式结果，支持多个材料 ID 输入，用 '.' 分隔。
    """,
    args_schema=GetFormationEnergyPerAtomInput,
    metadata={"args_schema_json": GetFormationEnergyPerAtomInput.schema()}
)

# ========================== 工具3: Stability check ==========================
class IsStableInput(BaseModel):
    material_id: str = Field(
        ..., description="材料 ID，可输入多个，用 '.' 分隔，例如 'mp-1.mp-555322'"
    )

async def is_stable_coroutine(material_id: str) -> Dict[str, Any]:
    """
    根据材料 ID 检查材料是否稳定 (is_stable)，返回 Markdown 格式结果。
    """
    try:
        cleaned_id = material_id.replace(" ", "").replace("\n", "").replace('"', "").replace("'", "")
        mpr = MPRester(api_key)
        id_list = cleaned_id.split(".")
        docs = mpr.materials.summary.search(material_ids=id_list)
        markdown = "## Check if material is stable:\n## Results:\n"
        if not docs:
            markdown += "No materials found"
        else:
            for doc in docs:
                markdown += f"**Input material id:** {doc.material_id}\t**Is stable:** {doc.is_stable}\n"
        return {"result": markdown}
    except Exception as e:
        logging.error(f"Error in is_stable_coroutine: {e}")
        return {"error": str(e)}

is_stable_tool = StructuredTool.from_function(
    coroutine=is_stable_coroutine,
    name=Tools.IS_STABLE,
    description="""
    【领域：材料科学】
    根据材料 ID 检查材料是否稳定 (is_stable)。
    返回 Markdown 格式结果，支持多个材料 ID 输入，用 '.' 分隔。
    """,
    args_schema=IsStableInput,
    metadata={"args_schema_json": IsStableInput.schema()}
)



# ===================== Tool 1: Get Structure Graph =====================

class GetStructureGraphInput(BaseModel):
    material_id: str = Field(
        ..., description="材料的 Material ID，只能输入一个，例如 'mp-149'。"
    )

async def get_structure_graph_coroutine(
    material_id: str
) -> Dict[str, str]:
    """
    获取指定 Material ID 的结构图，返回 Markdown 格式字符串。
    """
    try:
        cleaned_id = material_id.replace(" ", "").replace("\n", "").replace("\'", "").replace("\"", "")
        if "=" in cleaned_id:
            _, cleaned_id = cleaned_id.split("=")

        url = "https://api.materialsproject.org/materials/bonds/"
        params = {
            "material_ids": cleaned_id,
            "_per_page": 100,
            "_skip": 0,
            "_limit": 100,
            "_all_fields": "true"
        }
        headers = {
            "accept": "application/json",
            "X-API-KEY": api_key  # 请确保在环境中设置 api_key
        }

        response = requests.get(url, headers=headers, params=params)
        response.raise_for_status()
        data = response.json()

        material = data['data'][0]
        markdown_text = f"# Material Structure Graph\n" \
                        f"**Material ID**: {material['material_id']}\n" \
                        f"**Last Updated**: {material['last_updated']}\n\n"

        structure = material['structure_graph']['structure']
        lattice = structure['lattice']
        markdown_text += "## Structure Graph\n"
        markdown_text += "### Lattice Parameters\n"
        markdown_text += f"- a: {lattice['a']}, b: {lattice['b']}, c: {lattice['c']}\n"
        markdown_text += f"- Alpha: {lattice['alpha']}, Beta: {lattice['beta']}, Gamma: {lattice['gamma']}\n"
        markdown_text += f"- Volume: {lattice['volume']}\n"

        markdown_text += "### Sites Information\n"
        for site in structure['sites']:
            markdown_text += f"- Element: {site['species'][0]['element']}, Position: {site['xyz']}, Label: {site['label']}\n"

        markdown_text += "### Bonding Information\n"
        for adjacency_list in material['structure_graph']['graphs']['adjacency']:
            for bond in adjacency_list:
                markdown_text += f"- Bond from ID {bond['id']} to J-image {bond['to_jimage']} with weight {bond['weight']}\n"

        return {"structure_graph_markdown": markdown_text}

    except Exception as e:
        return {"error": f"获取结构图失败: {str(e)}"}


get_structure_graph_tool = StructuredTool.from_function(
    coroutine=get_structure_graph_coroutine,
    name=Tools.GET_STRUCTURE_GRAPH,
    description="""
    【领域：材料科学】
    根据 Material ID 获取材料结构图，返回 Markdown 格式文本，包括：
      - 材料 ID 和更新时间
      - 晶格参数
      - 原子位置信息
      - 键合信息
    """,
    args_schema=GetStructureGraphInput,
    metadata={"args_schema_json": GetStructureGraphInput.schema()}
)


