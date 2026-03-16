from pydantic import BaseModel, Field
from typing import Dict, Any, Optional
import logging
import asyncio
from pymatgen.ext.matproj import MPRester
from workflow.tools.chemistry.utils import is_multiple_smiles, split_smiles,tanimoto,is_smiles, pubchem_query2smiles
from langchain_core.tools import StructuredTool
from workflow.const import Tools

from workflow.utils.minio_utils import upload_content_to_minio
import aiohttp
from typing import List, Union

import pickle
from typing import Any
from minio.error import S3Error
import os as _os_mat
MP_API = _os_mat.environ.get("MP_API_KEY", "")

#from mp_api.client import MPRester
from io import BytesIO
from datetime import datetime
import pickle
import re
from datetime import datetime
from workflow import config as science_config
from workflow.tools.tools_config import DEEPSEEK_CHAT

def count_token(text: str) -> int:
    """
    Estimate token count based on whitespace and punctuation.
    This is not precise but fast.
    """
    # 按空格和常见标点分词
    tokens = text.replace("\n", " ").split()
    return len(tokens)


fields_to_remove = [
    "fields_not_requested",
    "builder_meta",
    "warnings",
    "fitting_data",
    "fitting_method",
    "state",
    "origins",
    "last_updated"
]

def remove_fields_from_docs(docs_list: list, fields_to_remove: list) -> list:
    """
    Removes specified fields from a list of documents.
    
    Args:
    docs_list (list): List of dictionaries (documents) to clean.
    fields_to_remove (list): List of field names to remove from each document.
    
    Returns:
    list: Cleaned list of documents without the specified fields.
    """
    cleaned_docs = []
    for doc in docs_list:
        if isinstance(doc, dict):
            cleaned_doc = {key: value for key, value in doc.items() if key not in fields_to_remove}
            cleaned_docs.append(cleaned_doc)
    return cleaned_docs

import json

MAX_DOC_LIMIT = 15
MAX_TOKENS = 2000  # 根据 DeepSeek 实际限制调整

def generate_summary(docs_list) -> dict:
    """
    Converts a list of various docs (ElasticityDoc, ElectronicStructureDoc, SurfacePropDoc, matweb data)
    into a concise text summary using DeepSeekV3. Returns a dictionary with success status, data, and raw response.
    """
    try:
        summaries = []

        for doc_list in docs_list[:MAX_DOC_LIMIT]:
            results_str = json.dumps(doc_list)

            if count_token(results_str) > MAX_TOKENS:
                continue

            system_prompt = (
                "You are a helpful assistant that generates concise, informative summaries. "
                "Highlight key insights, patterns, and most significant findings. "
                "Keep the summary under 300 words."
            )

            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"Please summarize the following results:\n{results_str}\nSummary:"}
            ]

            # 使用 DeepSeekV3 invoke 方法
            response = DEEPSEEK_CHAT.invoke(messages)

            # 提取文本内容
            if hasattr(response, 'content') and isinstance(response.content, str):
                response_text = response.content.strip()
            else:
                response_text = str(response).strip()

            summaries.append(response_text)

        return {
            "success": True,
            "data": " ".join(summaries),
            "raw_response": summaries
        }

    except Exception as e:
        return {
            "success": False,
            "error": f"Error querying DeepSeek: {str(e)}",
            "raw_response": summaries if 'summaries' in locals() else []
        }

matweb_property_fields = [
    "1% Secant Modulus (546 matls)",
    "1% Secant Modulus, MD (1953 matls)",
    "1% Secant Modulus, TD (1917 matls)",
    "2% Secant Modulus (546 matls)",
    "Arc Resistance (3268 matls)",
    "Charpy Impact (1055 matls)",
    "Charpy Impact Unnotched (11925 matls)",
    "Charpy Impact, Notched (16186 matls)",
    "Coefficient of Friction (3480 matls)",
    "Comparative Tracking Index (9096 matls)",
    "Compressive Modulus (1892 matls)",
    "Compressive Yield Strength (8620 matls)",
    "CTE, linear (29476 matls)",
    "CTE, linear, Transverse to Flow (7064 matls)",
    "Cure Time (4110 matls)",
    "Deflection Temperature at 0.46 MPa (66 psi) (24169 matls)",
    "Deflection Temperature at 1.8 MPa (264 psi) (35786 matls)",
    "Deflection Temperature at 8.0 MPa (895 matls)",
    "Density (108227 matls)",
    "Dielectric Constant (13463 matls)",
    "Dielectric Strength (15920 matls)",
    "Dissipation Factor (10601 matls)",
    "Drying Temperature (19391 matls)",
    "Electrical Resistivity (30440 matls)",
    "Elongation at Break (72346 matls)",
    "Elongation at Yield (14453 matls)",
    "Emissivity (0-1) (162 matls)",
    "Fatigue Strength (1166 matls)",
    "Film Elongation at Break, MD (3604 matls)",
    "Film Elongation at Break, TD (3361 matls)",
    "Film Elongation at Yield, MD (298 matls)",
    "Film Elongation at Yield, TD (255 matls)",
    "Film Tensile Strength at Break, MD (3775 matls)",
    "Film Tensile Strength at Break, TD (3522 matls)",
    "Film Tensile Strength at Yield, MD (1659 matls)",
    "Film Tensile Strength at Yield, TD (1631 matls)",
    "Flammability, UL94 (25332 matls)",
    "Flexural Modulus (45901 matls)",
    "Flexural Stiffness (45901 matls)",
    "Flexural Yield Strength (37318 matls)",
    "Fracture Toughness (608 matls)",
    "Gardner Impact (1578 matls)",
    "Glass Transition Temp, Tg (5864 matls)",
    "Gloss (3190 matls)",
    "Glow Wire Test (3959 matls)",
    "Hardness, Barcol (495 matls)",
    "Hardness, Brinell (4721 matls)",
    "Hardness, Knoop (3374 matls)",
    "Hardness, Rockwell A (667 matls)",
    "Hardness, Rockwell B (4155 matls)",
    "Hardness, Rockwell C (3210 matls)",
    "Hardness, Rockwell E (322 matls)",
    "Hardness, Rockwell M (3175 matls)",
    "Hardness, Rockwell R (9489 matls)",
    "Hardness, Shore A (17205 matls)",
    "Hardness, Shore D (11015 matls)",
    "Hardness, Vickers (4107 matls)",
    "Haze (5108 matls)",
    "Heat Distortion Temperature (377 matls)",
    "Heat of Fusion (1070 matls)",
    "Hot Ball Pressure Test (854 matls)",
    "Izod Impact (689 matls)",
    "Izod Impact, Notched (29459 matls)",
    "Izod Impact, Unnotched (10012 matls)",
    "K (wear) Factor (961 matls)",
    "Linear Mold Shrinkage (34696 matls)",
    "Liquidus (5121 matls)",
    "Magnetic Permeability (898 matls)",
    "Maximum Service Temperature, Air (20174 matls)",
    "Maximum Service Temperature, Inert (360 matls)",
    "Melt Flow (32725 matls)",
    "Melt Temperature (27542 matls)",
    "Melting Point (27230 matls)",
    "Minimum Service Temperature, Air (10058 matls)",
    "Modulus of Elasticity (41250 matls)",
    "Moisture Absorption at Equilibrium (9911 matls)",
    "Moisture Vapor Transmission (344 matls)",
    "Mold Temperature (25583 matls)",
    "Oxygen Index (5050 matls)",
    "Oxygen Transmission (585 matls)",
    "Poissons Ratio (7883 matls)",
    "Processing Temperature (11343 matls)",
    "Reflection Coefficient, Visible (0-1) (260 matls)",
    "Refractive Index (4704 matls)",
    "Ring & Ball Softening Point (430 matls)",
    "Rupture Strength (18 matls)",
    "Secant Modulus (546 matls)",
    "Shear Modulus (7784 matls)",
    "Shear Strength (4757 matls)",
    "Solidus (4854 matls)",
    "Specific Heat Capacity (9777 matls)",
    "Stiffness Modulus (45901 matls)",
    "Surface Resistance (12128 matls)",
    "Tack-Free Time (510 matls)",
    "Tear Strength (9151 matls)",
    "Tensile Modulus (41250 matls)",
    "Tensile Strength at Break (66430 matls)",
    "Tensile Strength, Ultimate (66430 matls)",
    "Tensile Strength, Yield (46238 matls)",
    "Thermal Conductivity (16755 matls)",
    "Transmission, Visible (6377 matls)",
    "UL RTI, Electrical (3287 matls)",
    "UL RTI, Mechanical with Impact (2989 matls)",
    "UL RTI, Mechanical without Impact (3002 matls)",
    "Vicat Softening Point (17839 matls)",
    "Water Absorption (18636 matls)",
    "Water Absorption at Saturation (4262 matls)"
]

# 测试成功
# 查询材料 ID 为 mp-149 的表面性质数据
class MPSurfacePropertiesInput(BaseModel):
    material_ids: Optional[Union[str, List[str]]] = Field(
        None, 
        description="A single Material ID string or list of strings (e.g., mp-149, [mp-149, mp-13])"
    )
    has_reconstructed: Optional[bool] = Field(
        None, 
        description="Whether the entry has any reconstructed surfaces."
    )
    shape_factor: Optional[List[Union[float, None]]] = Field(
        None, 
        description="Minimum and maximum shape factor values to consider.",
        min_items=2,
        max_items=2
    )
    surface_energy_anisotropy: Optional[List[Union[float, None]]] = Field(
        None, 
        description="Minimum and maximum surface energy anisotropy values to consider.",
        min_items=2,
        max_items=2
    )
    weighted_surface_energy: Optional[List[Union[float, None]]] = Field(
        None, 
        description="Minimum and maximum weighted surface energy in J/m² to consider.",
        min_items=2,
        max_items=2
    )
    weighted_work_function: Optional[List[Union[float, None]]] = Field(
        None, 
        description="Minimum and maximum weighted work function in eV to consider.",
        min_items=2,
        max_items=2
    )
    num_chunks: Optional[int] = Field(
        None, 
        description="Maximum number of chunks of data to yield. None will yield all possible."
    )
    chunk_size: int = Field(
        1000, 
        description="Number of data entries per chunk."
    )
    all_fields: bool = Field(
        True, 
        description="Whether to return all fields in the document. Defaults to True."
    )
    fields: Optional[List[str]] = Field(
        None, 
        description="List of fields in SurfacePropDoc to return data for. Default is material_id only if all_fields is False."
    )
async def mp_surface_properties_coroutine(**kwargs) -> Dict[str, Any]:
    """
    查询 Materials Project 的表面性质数据：
    - 可通过 material_ids、形状因子、表面能各向异性等筛选
    - 返回 JSON 数据，上传到 MinIO 并返回预签名 URL
    """
    try:


        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        mpr = MPRester(MP_API)
        # 查询数据
        results = mpr.materials.surface_properties.search(**kwargs)
        docs_as_dicts = [doc.dict() for doc in results]

        # 可选字段移除
        fields_to_remove = kwargs.get("fields_to_remove", [])
        docs_as_dicts = remove_fields_from_docs(docs_as_dicts, fields_to_remove)

        # 上传 JSON 到 MinIO 而非本地保存
        buffer = BytesIO()
        json_bytes = json.dumps(docs_as_dicts).encode("utf-8")
        buffer.write(json_bytes)
        buffer.seek(0)
        file_name = f"surface_properties_{timestamp}.json"

        file_url = await upload_content_to_minio(
            content=buffer.getvalue(),
            file_name=file_name,
            file_extension=".json",
            content_type="application/json",
            no_expired=True
        )

        # 可选返回 summary
        summary = generate_summary(docs_as_dicts)
        return {"summary": summary, "file_url": file_url}

    except Exception as e:
        return {"error": f"查询或上传 Materials Project 表面性质失败: {str(e)}"}

mp_surface_properties_tool = StructuredTool.from_function(
    coroutine=mp_surface_properties_coroutine,
    name=Tools.MaterialsProjectSurfaceProperties,
    description="""
使用 Materials Project API 查询材料表面性质。
可根据材料 ID、形状因子、表面能各向异性、加权表面能、加权功函数等条件筛选数据。
输出包括：
- JSON 文件 URL（上传到 MinIO）
- 查询结果摘要 summary
""",
    args_schema=MPSurfacePropertiesInput,
    metadata={"args_schema_json": MPSurfacePropertiesInput.schema()}
)

# -----------------------------
# 工具2
# -----------------------------
class MPThermoInput(BaseModel):
    material_ids: Optional[Union[str, List[str]]] = Field(
        None, description="A single Material ID string or list of strings (e.g., mp-149, [mp-149, mp-13])."
    )
    chemsys: Optional[Union[str, List[str]]] = Field(
        None, description="A chemical system or list of chemical systems (e.g., Li-Fe-O, Si-*, [Si-O, Li-Fe-P])."
    )
    energy_above_hull: Optional[List[Union[float, None]]] = Field(
        None, description="Min and max energy above hull in eV/atom.", min_items=2, max_items=2
    )
    equilibrium_reaction_energy: Optional[List[Union[float, None]]] = Field(
        None, description="Min and max equilibrium reaction energy in eV/atom.", min_items=2, max_items=2
    )
    formation_energy: Optional[List[Union[float, None]]] = Field(
        None, description="Min and max formation energy in eV/atom.", min_items=2, max_items=2
    )
    formula: Optional[Union[str, List[str]]] = Field(
        None, description="Chemical formula with optional wildcards (e.g., Fe2O3, ABO3, Si*)."
    )
    is_stable: Optional[bool] = Field(None, description="Whether the material is stable.")
    num_elements: Optional[List[Union[float, None]]] = Field(
        None, description="Min and max number of elements.", min_items=2, max_items=2
    )
    thermo_ids: Optional[List[str]] = Field(
        None, description="List of thermo IDs (e.g., mp-149_GGA_GGA+U)."
    )
    # thermo_types: Optional[List[Union[ThermoType, str]]] = Field(
    #     None, description="List of thermo types to return data for."
    # )
    total_energy: Optional[List[Union[float, None]]] = Field(
        None, description="Min and max corrected total energy in eV/atom.", min_items=2, max_items=2
    )
    uncorrected_energy: Optional[List[Union[float, None]]] = Field(
        None, description="Min and max uncorrected total energy in eV/atom.", min_items=2, max_items=2
    )
    num_chunks: Optional[int] = Field(None, description="Maximum number of chunks; None for all.")
    chunk_size: int = Field(1000, description="Number of entries per chunk.")
    all_fields: bool = Field(True, description="Whether to return all fields. Defaults to True.")
    fields: Optional[List[str]] = Field(
        None, description="Specific fields to return if all_fields=False."
    )

async def mp_thermo_coroutine(**kwargs) -> dict:
    """
    Query core Materials Project thermo data based on filters like:
    - material_ids, chemsys, formula
    - is_stable, num_elements, energy/formation energies
    Returns the results as a JSON file uploaded to MinIO and a presigned URL.
    """
    try:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename_base = f"thermo_{timestamp}.json"

        # 查询数据
        with MPRester(MP_API, mute_progress_bars=True) as mpr:
            results = mpr.materials.thermo.search(**kwargs)

        docs_as_dicts = [doc.dict() for doc in results]
        docs_as_dicts = remove_fields_from_docs(docs_as_dicts, fields_to_remove)

        # 序列化并上传到 MinIO
        buffer = BytesIO()
        buffer.write(json.dumps(docs_as_dicts).encode("utf-8"))
        buffer.seek(0)
        file_url = await upload_content_to_minio(
            content=buffer.getvalue(),
            file_name=filename_base,
            file_extension=".json",
            content_type="application/json",
            no_expired=True,
        )
        summary = generate_summary(docs_as_dicts)
        return {"summary": summary, "thermo_file_url": file_url}

    except Exception as e:
        return {"error": f"查询或上传材料热力学数据失败: {str(e)}"}

mp_thermo_tool = StructuredTool.from_function(
    coroutine=mp_thermo_coroutine,
    name=Tools.MaterialsProjectThermo,
    description="""
Query core Materials Project thermo data with multiple filter options:
- is_stable (bool): Filter by material stability.
- material_ids, chemsys, formula
- thermo_ids, thermo_types
- energy_above_hull, equilibrium_reaction_energy, formation_energy
- total_energy, uncorrected_energy
- num_elements
- num_chunks, chunk_size
Returns both a JSON file URL and a summary of the results.
""",
    args_schema=MPThermoInput,
    metadata={"args_schema_json": MPThermoInput.schema()}
)



# -----------------------------
# 工具3
# -----------------------------
class MPDielectricInput(BaseModel):
    material_ids: Optional[Union[str, List[str]]] = Field(
        None, description="Single Material ID or list of IDs (e.g., mp-149, [mp-149, mp-13])."
    )
    e_total: Optional[List[Union[float, None]]] = Field(
        None, description="Min and max total dielectric constant.", min_items=2, max_items=2
    )
    e_ionic: Optional[List[Union[float, None]]] = Field(
        None, description="Min and max ionic dielectric constant.", min_items=2, max_items=2
    )
    e_electronic: Optional[List[Union[float, None]]] = Field(
        None, description="Min and max electronic dielectric constant.", min_items=2, max_items=2
    )
    n: Optional[List[Union[float, None]]] = Field(
        None, description="Min and max refractive index.", min_items=2, max_items=2
    )
    num_chunks: Optional[int] = Field(None, description="Maximum number of chunks; None for all.")
    chunk_size: int = Field(1000, description="Number of entries per chunk.")
    all_fields: bool = Field(True, description="Return all fields (default: True).")
    fields: Optional[List[str]] = Field(
        None, description="Specific fields to return if all_fields=False."
    )


async def mp_dielectric_coroutine(**kwargs) -> dict:
    """
    Query Materials Project dielectric data based on filters like:
    - material_ids, e_total, e_ionic, e_electronic, n
    Returns JSON file uploaded to MinIO and a summary.
    """
    try:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename_base = f"dielectric_{timestamp}.json"

        with MPRester(MP_API, mute_progress_bars=True) as mpr:
            results = mpr.materials.dielectric.search(**kwargs)

        docs_as_dicts = [doc.dict() for doc in results]
        docs_as_dicts = remove_fields_from_docs(docs_as_dicts, fields_to_remove)

        # 序列化并上传 MinIO
        buffer = BytesIO()
        buffer.write(json.dumps(docs_as_dicts).encode("utf-8"))
        buffer.seek(0)
        file_url = await upload_content_to_minio(
            content=buffer.getvalue(),
            file_name=filename_base,
            file_extension=".json",
            content_type="application/json",
            no_expired=True,
        )
        summary = generate_summary(docs_as_dicts)
        return {"summary": summary, "dielectric_file_url": file_url}

    except Exception as e:
        return {"error": f"查询或上传材料介电数据失败: {str(e)}"}

mp_dielectric_tool = StructuredTool.from_function(
    coroutine=mp_dielectric_coroutine,
    name=Tools.MaterialsProjectDielectric,
    description="""
Query Materials Project dielectric data with multiple filter options:
- material_ids (str or list): Single or multiple Material IDs (e.g., mp-149)
- e_total, e_ionic, e_electronic: Ranges for dielectric constants
- n: Range for refractive index
- num_chunks, chunk_size: Pagination options
- all_fields: Return all fields (default: True)
- fields: Specific fields to return if all_fields=False
Returns both a JSON file URL and a summary.
""",
    args_schema=MPDielectricInput,
    metadata={"args_schema_json": MPDielectricInput.schema()}
)


# -----------------------------
# 工具4
# -----------------------------
class MPPiezoelectricInput(BaseModel):
    material_ids: Optional[Union[str, List[str]]] = Field(
        None, 
        description="A single Material ID string or list of strings (e.g., mp-149, [mp-149, mp-13])."
    )
    piezoelectric_modulus: Optional[List[Union[float, None]]] = Field(
        None, 
        description="Minimum and maximum value of the piezoelectric modulus in C/m² to consider.",
        min_items=2,
        max_items=2
    )
    num_chunks: Optional[int] = Field(
        None, 
        description="Maximum number of chunks of data to yield. None will yield all possible."
    )
    chunk_size: int = Field(
        1000, 
        description="Number of data entries per chunk."
    )
    all_fields: bool = Field(
        True, 
        description="Whether to return all fields in the document. Defaults to True."
    )
    fields: Optional[List[str]] = Field(
        None, 
        description="List of fields in PiezoDoc to return data for. Default is material_id and last_updated if all_fields is False."
    )

async def get_piezoelectric_data_coroutine(**kwargs) -> Dict[str, Any]:
    """
    查询材料项目（Materials Project）中的压电性质数据，
    并将结果序列化为 JSON 上传到 MinIO，返回预签名 URL。

    支持的查询参数：
      - material_ids : str 或 List[str]，材料 ID
      - piezoelectric_modulus : [min, max]，压电模量范围 C/m²
      - num_chunks : int，分块获取最大数量
      - chunk_size : int，每块数据条数
      - all_fields : bool，是否返回所有字段
      - fields : List[str]，指定返回的字段列表
    """
    try:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        with MPRester(MP_API, mute_progress_bars=True) as mpr:
            results = mpr.materials.piezoelectric.search(**kwargs)

        # 转 dict 并移除不需要字段
        docs_as_dicts = [doc.dict() for doc in results]
        docs_as_dicts = remove_fields_from_docs(docs_as_dicts, fields_to_remove=None)

        # 序列化 JSON 到内存
        buffer = BytesIO()
        buffer.write(json.dumps(docs_as_dicts, indent=2).encode("utf-8"))
        buffer.seek(0)
        data = buffer.getvalue()

        # 上传到 MinIO
        file_name = f"piezoelectric_{timestamp}.json"
        file_url = await upload_content_to_minio(
            content=data,
            file_name=file_name,
            file_extension=".json",
            content_type="application/json",
            no_expired=True,
        )

        # 返回 URL 和摘要
        summary = generate_summary(docs_as_dicts)
        return {"file_url": file_url, "summary": summary}

    except Exception as e:
        return {"error": f"查询或上传压电数据失败: {str(e)}"}


get_piezoelectric_data_tool = StructuredTool.from_function(
    coroutine=get_piezoelectric_data_coroutine,
    name=Tools.MaterialsProjectPiezoelectric,
    description="""
    查询 Materials Project 的压电数据，并返回 JSON 文件 URL 和摘要。
    查询可选参数：
      - material_ids : str 或 List[str]，材料 ID
      - piezoelectric_modulus : [min, max]，压电模量范围 C/m²
      - num_chunks : int，分块获取最大数量
      - chunk_size : int，每块数据条数
      - all_fields : bool，是否返回所有字段
      - fields : List[str]，指定返回的字段列表
    """,
    args_schema=MPPiezoelectricInput,
    metadata={"args_schema_json": MPPiezoelectricInput.schema()}
)
# -----------------------------
# 工具6
# -----------------------------


class MPSynthesisInput(BaseModel):
    keywords: Optional[List[str]] = Field(
        None,
        description="List of string keywords to search synthesis paragraph text with."
    )
    # synthesis_type: Optional[List[SynthesisTypeEnum]] = Field(
    #     None,
    #     description="Type of synthesis to include, defined by SynthesisTypeEnum."
    # )
    target_formula: Optional[str] = Field(
        None,
        description="Chemical formula of the target material."
    )
    precursor_formula: Optional[str] = Field(
        None,
        description="Chemical formula of the precursor material."
    )
    # operations: Optional[List[OperationTypeEnum]] = Field(
    #     None,
    #     description="List of operations that syntheses must have, defined by OperationTypeEnum."
    # )
    condition_heating_temperature_min: Optional[float] = Field(
        None,
        description="Minimal heating temperature in the synthesis process."
    )
    condition_heating_temperature_max: Optional[float] = Field(
        None,
        description="Maximal heating temperature in the synthesis process."
    )
    condition_heating_time_min: Optional[float] = Field(
        None,
        description="Minimal heating time in the synthesis process."
    )
    condition_heating_time_max: Optional[float] = Field(
        None,
        description="Maximal heating time in the synthesis process."
    )
    condition_heating_atmosphere: Optional[List[str]] = Field(
        None,
        description='Required heating atmosphere, such as "air", "argon".'
    )
    condition_mixing_device: Optional[List[str]] = Field(
        None,
        description='Required mixing device, such as "zirconia", "Al2O3".'
    )
    condition_mixing_media: Optional[List[str]] = Field(
        None,
        description='Required mixing media, such as "alcohol", "water".'
    )
    num_chunks: Optional[int] = Field(
        None,
        description="Maximum number of chunks of data to yield. None will yield all possible."
    )
    chunk_size: int = Field(
        10,
        description="Number of data entries per chunk."
    )

async def mp_synthesis_coroutine(**kwargs) -> Dict[str, Any]:
    """
    Search synthesis recipes from Materials Project database using given parameters.
    Results are serialized to JSON and uploaded to MinIO; a presigned URL is returned.
    """
    try:
        mpr = MPRester(MP_API)
        results = mpr.materials.synthesis.search(**kwargs)
        docs_as_dicts = [doc.dict() for doc in results]
        docs_as_dicts = remove_fields_from_docs(docs_as_dicts, fields_to_remove)

        # JSON 序列化到内存
        json_bytes = json.dumps(docs_as_dicts, ensure_ascii=False).encode('utf-8')
        buffer = BytesIO(json_bytes)
        buffer.seek(0)

        # 构造文件名
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        file_name = f"synthesis_{timestamp}.json"

        # 上传到 MinIO
        file_url = await upload_content_to_minio(
            content=buffer.getvalue(),
            file_name=file_name,
            file_extension=".json",
            content_type="application/json",
            no_expired=True,
        )

        # 返回 summary 与 URL
        summary = generate_summary(docs_as_dicts)
        return {
            "summary": summary,
            "synthesis_file_url": file_url
        }

    except S3Error as e:
        return {"error": f"MinIO 上传失败: {e.code} - {e.message}"}
    except Exception as e:
        return {"error": f"合成搜索或上传失败: {str(e)}"}

mp_synthesis_tool = StructuredTool.from_function(
    coroutine=mp_synthesis_coroutine,
    name=Tools.MaterialsProjectSynthesis,
    description="""
    使用 Materials Project API 搜索材料合成路线：
    - 可按 synthesis_type, target_formula, precursor_formula, operations 等筛选
    - 可按加热温度/时间、气氛、搅拌设备/介质等条件过滤
    - 支持分块返回 num_chunks 和 chunk_size
    返回：
    - summary: 搜索结果摘要
    - synthesis_file_url: 搜索结果 JSON 文件 MinIO URL
    """,
    args_schema=MPSynthesisInput,
    metadata={"args_schema_json": MPSynthesisInput.schema()}
)

# -----------------------------
# 工具7
# -----------------------------

class MPElectronicStructureInput(BaseModel):
    material_ids: Optional[Union[str, List[str]]] = Field(
        None,
        description="A single Material ID string or list of strings (e.g., 'mp-149' or ['mp-149', 'mp-13'])."
    )
    band_gap: Optional[List[Union[float, None]]] = Field(
        None,
        description="Minimum and maximum band gap in eV to consider.",
        min_items=2,
        max_items=2
    )
    chemsys: Optional[Union[str, List[str]]] = Field(
        None,
        description="A chemical system or list of systems (e.g., 'Li-Fe-O', 'Si-*')."
    )
    efermi: Optional[List[Union[float, None]]] = Field(
        None,
        description="Minimum and maximum Fermi energy in eV to consider.",
        min_items=2,
        max_items=2
    )
    elements: Optional[List[str]] = Field(
        None,
        description="A list of elements to include."
    )
    exclude_elements: Optional[List[str]] = Field(
        None,
        description="A list of elements to exclude."
    )
    formula: Optional[Union[str, List[str]]] = Field(
        None,
        description="Chemical formula (e.g., 'Fe2O3', 'ABO3', 'Si*') or list of formulas."
    )
    is_gap_direct: Optional[bool] = Field(
        None,
        description="Whether the material has a direct band gap."
    )
    is_metal: Optional[bool] = Field(
        None,
        description="Whether the material is considered a metal."
    )
    # magnetic_ordering: Optional[Ordering] = Field(
    #     None,
    #     description="Magnetic ordering of the material."
    # )
    num_elements: Optional[List[Union[int, None]]] = Field(
        None,
        description="Minimum and maximum number of elements in the composition.",
        min_items=2,
        max_items=2
    )
    num_chunks: Optional[int] = Field(
        None,
        description="Maximum number of chunks of data to yield. None will yield all possible."
    )
    chunk_size: int = Field(
        1000,
        description="Number of data entries per chunk."
    )
    all_fields: bool = Field(
        True,
        description="Whether to return all fields in the document. Defaults to True."
    )
    fields: Optional[List[str]] = Field(
        None,
        description="List of specific fields to return. Defaults to ['material_id', 'last_updated'] if all_fields=False."
    )

async def mp_electronic_structure_coroutine(**kwargs) -> Dict[str, Any]:
    """
    Query Materials Project electronic structure data with given filters.
    Results are serialized to JSON and uploaded to MinIO; presigned URL is returned.
    """
    try:
        mpr = MPRester(MP_API)
        results = mpr.materials.electronic_structure.search(**kwargs)
        docs_as_dicts = [doc.dict() for doc in results]
        docs_as_dicts = remove_fields_from_docs(docs_as_dicts, fields_to_remove)

        # JSON 序列化到内存
        json_bytes = json.dumps(docs_as_dicts, ensure_ascii=False).encode('utf-8')
        buffer = BytesIO(json_bytes)
        buffer.seek(0)

        # 构造文件名
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        file_name = f"electronic_structure_{timestamp}.json"

        # 上传到 MinIO
        file_url = await upload_content_to_minio(
            content=buffer.getvalue(),
            file_name=file_name,
            file_extension=".json",
            content_type="application/json",
            no_expired=True,
        )

        # 返回 summary 与 URL
        summary = generate_summary(docs_as_dicts)
        return {
            "summary": summary,
            "electronic_structure_file_url": file_url
        }

    except S3Error as e:
        return {"error": f"MinIO 上传失败: {e.code} - {e.message}"}
    except Exception as e:
        return {"error": f"电子结构查询或上传失败: {str(e)}"}

mp_electronic_structure_tool = StructuredTool.from_function(
    coroutine=mp_electronic_structure_coroutine,
    name=Tools.MaterialsProjectElectronicStructure,
    description="""
    使用 Materials Project API 查询材料电子结构数据：
    - 可按 material_ids、band_gap、chemsys、efermi、elements、exclude_elements、formula 等筛选
    - 可按 is_gap_direct、is_metal、magnetic_ordering、num_elements 等条件过滤
    - 支持分块返回 num_chunks 和 chunk_size
    - 可选择返回所有字段或部分字段 (all_fields / fields)
    返回：
    - summary: 搜索结果摘要
    - electronic_structure_file_url: 查询结果 JSON 文件 MinIO URL
    """,
    args_schema=MPElectronicStructureInput,
    metadata={"args_schema_json": MPElectronicStructureInput.schema()}
)

# -----------------------------
# 工具8
# -----------------------------

class MPElectronicBandStructureInput(BaseModel):
    band_gap: Optional[List[Union[float, None]]] = Field(
        None,
        description="Minimum and maximum band gap in eV to consider.",
        min_items=2,
        max_items=2
    )
    efermi: Optional[List[Union[float, None]]] = Field(
        None,
        description="Minimum and maximum Fermi energy in eV to consider.",
        min_items=2,
        max_items=2
    )
    is_gap_direct: Optional[bool] = Field(
        None,
        description="Whether the material has a direct band gap."
    )
    is_metal: Optional[bool] = Field(
        None,
        description="Whether the material is considered a metal."
    )
    magnetic_ordering: Optional[str] = Field(
        None,
        description="Magnetic ordering of the material."
    )
    path_type: str = Field(
        "setyawan_curtarolo",
        description="k-path selection convention for the band structure."
    )
    num_chunks: Optional[int] = Field(
        None,
        description="Maximum number of chunks of data to yield. None will yield all possible."
    )
    chunk_size: int = Field(
        1000,
        description="Number of data entries per chunk."
    )
    all_fields: bool = Field(
        True,
        description="Whether to return all fields in the document. Defaults to True."
    )
    fields: Optional[List[str]] = Field(
        None,
        description=(
            "List of fields in the electronic structure document to return data for. "
            "Defaults to 'material_id' and 'last_updated' if 'all_fields' is False."
        )
    )

async def mp_electronic_band_structure_coroutine(
    **kwargs
) -> Dict[str, Any]:
    """
    查询材料项目（Materials Project）电子能带结构数据，
    支持根据 band_gap、Fermi 能级、直接间隙、金属特性、磁性、k-path 类型等进行筛选。
    返回 JSON 数据上传到 MinIO 的预签名 URL，并提供摘要信息。
    """
    try:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        # 初始化 MPRester
        with MPRester(MP_API, mute_progress_bars=True) as mpr:
            results = mpr.materials.electronic_structure_bandstructure.search(**kwargs)

        # 转成 dict 并删除不需要的字段
        docs_as_dicts = [doc.dict() for doc in results]
        fields_to_remove = []  # 根据需要定义哪些字段不返回
        docs_as_dicts = remove_fields_from_docs(docs_as_dicts, fields_to_remove)

        # 序列化并上传到 MinIO
        json_data = json.dumps(docs_as_dicts).encode("utf-8")
        file_name = f"electronic_band_structure_{timestamp}.json"
        file_url = await upload_content_to_minio(
            content=json_data,
            file_name=file_name,
            file_extension=".json",
            content_type="application/json",
            no_expired=True,
        )

        # 生成摘要
        summary = generate_summary(docs_as_dicts)

        return {
            "file_url": file_url,
            "summary": summary,
            "num_results": len(docs_as_dicts)
        }

    except S3Error as e:
        return {"error": f"MinIO 上传失败: {e.code} - {e.message}"}
    except Exception as e:
        return {"error": f"查询或处理电子能带数据失败: {str(e)}"}

mp_electronic_band_structure_tool = StructuredTool.from_function(
    coroutine=mp_electronic_band_structure_coroutine,
    name=Tools.MaterialsProjectElectronicBandStructure,
    description="""
    查询材料项目（Materials Project）电子能带结构数据。
    支持按以下条件筛选：
      - band_gap (eV 范围)
      - efermi (Fermi 能级范围)
      - is_gap_direct (是否直接间隙)
      - is_metal (是否金属)
      - magnetic_ordering (磁性类型)
      - path_type (k-path 选择方式)
      - num_chunks, chunk_size (分页控制)
      - all_fields, fields (返回字段控制)
    返回：
      - JSON 文件 URL (上传至 MinIO)
      - 数据摘要
      - 数据条目数量
    """,
    args_schema=MPElectronicBandStructureInput,
    metadata={"args_schema_json": MPElectronicBandStructureInput.schema()}
)


# -----------------------------
# 工具10
# -----------------------------

class MPOxidationStatesInput(BaseModel):
    material_ids: Optional[Union[str, List[str]]] = Field(
        None,
        description="单个或多个 Material ID，例如 'mp-149' 或 ['mp-149', 'mp-13']"
    )
    chemsys: Optional[Union[str, List[str]]] = Field(
        None,
        description="化学体系，例如 'Li-Fe-O'、'Si-*' 或 ['Si-O', 'Li-Fe-P']"
    )
    formula: Optional[Union[str, List[str]]] = Field(
        None,
        description="化学式，可使用通配符，例如 'Fe2O3', 'ABO3', 'Si*'，也可以传入列表"
    )
    possible_species: Optional[Union[str, List[str]]] = Field(
        None,
        description="指定元素及其氧化态列表，例如 ['Cr2+', 'O2-']"
    )
    num_chunks: Optional[int] = Field(
        None,
        description="最大数据块数量，None 表示返回所有数据"
    )
    chunk_size: int = Field(
        1000,
        description="每个数据块包含的条目数"
    )
    all_fields: bool = Field(
        True,
        description="是否返回文档中的所有字段，默认 True"
    )
    fields: Optional[List[str]] = Field(
        None,
        description="若 all_fields=False，则指定返回哪些字段，默认 material_id、last_updated、formula_pretty"
    )

async def get_oxidation_states_coroutine(
    material_ids: Optional[Union[str, List[str]]] = None,
    chemsys: Optional[Union[str, List[str]]] = None,
    formula: Optional[Union[str, List[str]]] = None,
    possible_species: Optional[Union[str, List[str]]] = None,
    num_chunks: Optional[int] = None,
    chunk_size: int = 1000,
    all_fields: bool = True,
    fields: Optional[List[str]] = None
) -> Dict[str, Any]:
    """
    查询材料项目数据库中的氧化态信息，返回结果 JSON 文件的 MinIO URL。
    """
    try:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename_base = f"oxidation_states_{timestamp}.json"

        with MPRester(MP_API, mute_progress_bars=True) as mpr:
            results = mpr.materials.oxidation_states.search(
                material_ids=material_ids,
                chemsys=chemsys,
                formula=formula,
                possible_species=possible_species,
                num_chunks=num_chunks,
                chunk_size=chunk_size,
                all_fields=all_fields,
                fields=fields
            )

        # 转 dict 并可删除多余字段
        docs_as_dicts = [doc.dict() for doc in results]
        docs_as_dicts = remove_fields_from_docs(docs_as_dicts, fields_to_remove=[])  # 可指定需删除字段

        # 转成二进制上传
        buffer = BytesIO(json.dumps(docs_as_dicts, ensure_ascii=False).encode('utf-8'))
        buffer.seek(0)
        data = buffer.getvalue()

        # 上传到 MinIO
        file_url = await upload_content_to_minio(
            content=data,
            file_name=filename_base,
            file_extension=".json",
            content_type="application/json",
            no_expired=True
        )

        summary = generate_summary(docs_as_dicts)
        return {"summary": summary, "oxidation_states_file_url": file_url}

    except Exception as e:
        return {"error": f"查询或上传氧化态信息失败: {str(e)}"}


oxidation_states_tool = StructuredTool.from_function(
    coroutine=get_oxidation_states_coroutine,
    name=Tools.MaterialsProjectOxidationStates,
    description="""
    查询材料项目数据库中的氧化态信息：
      - 输入 material_ids, chemsys, formula, possible_species, num_chunks, chunk_size, all_fields, fields
      - 返回包含查询结果的 JSON 文件 MinIO URL 和简要汇总 summary
    """,
    args_schema=MPOxidationStatesInput,
    metadata={"args_schema_json": MPOxidationStatesInput.schema()}
)
# -----------------------------
# 工具11
# -----------------------------

class MPBondsInput(BaseModel):
    material_ids: Optional[Union[str, List[str]]] = Field(
        None,
        description="指定 Material ID 或 ID 列表，例如 'mp-149' 或 ['mp-149', 'mp-13']"
    )
    coordination_envs: Optional[List[str]] = Field(
        None,
        description="感兴趣的配位环境列表，例如 ['Mo-S(6)', 'S-Mo(3)']"
    )
    coordination_envs_anonymous: Optional[List[str]] = Field(
        None,
        description="匿名配位环境列表，例如 ['A-B(6)', 'A-B(3)']"
    )
    max_bond_length: Optional[List[Union[float, None]]] = Field(
        None,
        description="结构中最大键长的最小值和最大值",
        min_items=2,
        max_items=2
    )
    mean_bond_length: Optional[List[Union[float, None]]] = Field(
        None,
        description="结构中平均键长的最小值和最大值",
        min_items=2,
        max_items=2
    )
    min_bond_length: Optional[List[Union[float, None]]] = Field(
        None,
        description="结构中最小键长的最小值和最大值",
        min_items=2,
        max_items=2
    )
    num_chunks: Optional[int] = Field(
        None,
        description="最大数据块数量，None 表示返回所有数据"
    )
    chunk_size: int = Field(
        1000,
        description="每个数据块包含的条目数"
    )
    all_fields: bool = Field(
        True,
        description="是否返回文档中的所有字段，默认 True"
    )
    fields: Optional[List[str]] = Field(
        None,
        description="若 all_fields=False，则指定返回哪些字段，默认 material_id 和 last_updated"
    )

async def get_bonds_coroutine(
    material_ids: Optional[Union[str, List[str]]] = None,
    coordination_envs: Optional[List[str]] = None,
    coordination_envs_anonymous: Optional[List[str]] = None,
    max_bond_length: Optional[List[Union[float, None]]] = None,
    mean_bond_length: Optional[List[Union[float, None]]] = None,
    min_bond_length: Optional[List[Union[float, None]]] = None,
    num_chunks: Optional[int] = None,
    chunk_size: int = 1000,
    all_fields: bool = True,
    fields: Optional[List[str]] = None
) -> Dict[str, Any]:
    """
    查询材料项目数据库中的键合信息，返回结果 JSON 文件的 MinIO URL 和摘要。
    """
    try:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename_base = f"bonds_{timestamp}.json"

        with MPRester(MP_API, mute_progress_bars=True) as mpr:
            results = mpr.materials.bonds.search(
                material_ids=material_ids,
                coordination_envs=coordination_envs,
                coordination_envs_anonymous=coordination_envs_anonymous,
                max_bond_length=max_bond_length,
                mean_bond_length=mean_bond_length,
                min_bond_length=min_bond_length,
                num_chunks=num_chunks,
                chunk_size=chunk_size,
                all_fields=all_fields,
                fields=fields
            )

        # 转 dict 并可删除多余字段
        docs_as_dicts = [doc.dict() for doc in results]
        docs_as_dicts = remove_fields_from_docs(docs_as_dicts, fields_to_remove=[])

        # 转成二进制上传
        buffer = BytesIO(json.dumps(docs_as_dicts, ensure_ascii=False).encode('utf-8'))
        buffer.seek(0)
        data = buffer.getvalue()

        # 上传到 MinIO
        file_url = await upload_content_to_minio(
            content=data,
            file_name=filename_base,
            file_extension=".json",
            content_type="application/json",
            no_expired=True
        )

        summary = generate_summary(docs_as_dicts)
        return {"summary": summary, "bonds_file_url": file_url}

    except Exception as e:
        return {"error": f"查询或上传键合信息失败: {str(e)}"}

bonds_tool = StructuredTool.from_function(
    coroutine=get_bonds_coroutine,
    name=Tools.MaterialsProjectBonds,
    description="""
    查询材料项目数据库中的键合信息：
      - 输入 material_ids, coordination_envs, coordination_envs_anonymous, 
        max_bond_length, mean_bond_length, min_bond_length, 
        num_chunks, chunk_size, all_fields, fields
      - 返回包含查询结果的 JSON 文件 MinIO URL 和简要汇总 summary
    """,
    args_schema=MPBondsInput,
    metadata={"args_schema_json": MPBondsInput.schema()}
)

# -----------------------------
# 工具12
# -----------------------------

class MPAbsorptionInput(BaseModel):
    material_ids: Optional[Union[str, List[str]]] = Field(
        None,
        description=(
            "搜索指定 Material IDs 的光学吸收数据，支持单个 ID 或 ID 列表 "
            "(例如 'mp-149' 或 ['mp-149', 'mp-13'])"
        )
    )
    chemsys: Optional[Union[str, List[str]]] = Field(
        None,
        description=(
            "化学体系或化学体系列表进行搜索，例如 'Li-Fe-O', 'Si-*' 或 ['Si-O', 'Li-Fe-P']"
        )
    )
    elements: Optional[List[str]] = Field(
        None,
        description="搜索中包含的元素列表，例如 ['Li', 'Fe']"
    )
    exclude_elements: Optional[List[str]] = Field(
        None,
        description="搜索中排除的元素列表，例如 ['O', 'N']"
    )
    formula: Optional[Union[str, List[str]]] = Field(
        None,
        description=(
            "化学式或化学式列表，可包含匿名化或通配符，例如 'Fe2O3', 'ABO3', 'Si*' "
            "或者 ['Fe2O3', 'ABO3']"
        )
    )
    num_chunks: Optional[int] = Field(
        None, description="最大数据块数量，None 表示返回所有可能的数据块"
    )
    chunk_size: int = Field(
        1000, description="每个数据块包含的数据条目数量"
    )
    all_fields: bool = Field(
        True, description="是否返回文档中所有字段，默认 True"
    )
    fields: Optional[List[str]] = Field(
        None, description="返回 AbsorptionDoc 中的指定字段，若 all_fields 为 False，则默认返回 material_id 和 last_updated"
    )


async def mp_absorption_coroutine(**kwargs) -> Dict[str, Any]:
    """
    查询光学吸收数据：
      - 可基于 material_ids, chemsys, elements, exclude_elements, formula 进行搜索
      - 支持数据分页（num_chunks, chunk_size）
      - 可选择返回所有字段或指定字段
    结果以 JSON 序列化后上传到 MinIO，返回文件的预签名 URL。
    """
    try:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        file_name = f"absorption_{timestamp}.json"

        with MPRester(MP_API, mute_progress_bars=True) as mpr:
            results = mpr.materials.absorption.search(**kwargs)

        # 转为 dict 并清理不需要字段
        docs_as_dicts = [doc.dict() for doc in results]
        docs_as_dicts = remove_fields_from_docs(docs_as_dicts, fields_to_remove=kwargs.get("fields_to_remove", []))

        # JSON 序列化上传
        buffer = BytesIO()
        buffer.write(json.dumps(docs_as_dicts, ensure_ascii=False, indent=2).encode())
        buffer.seek(0)
        data = buffer.getvalue()

        file_url = await upload_content_to_minio(
            content=data,
            file_name=file_name,
            file_extension=".json",
            content_type="application/json",
            no_expired=True,
        )

        return {"absorption_data_file_url": file_url}

    except Exception as e:
        return {"error": f"光学吸收数据查询失败: {str(e)}"}


mp_absorption_tool = StructuredTool.from_function(
    coroutine=mp_absorption_coroutine,
    name=Tools.MaterialsProjectAbsorption,
    description="""
查询材料项目（Materials Project）中的光学吸收谱数据。
支持以下参数：
- material_ids: 指定 Material IDs
- chemsys: 化学体系或体系列表
- elements: 包含的元素
- exclude_elements: 排除的元素
- formula: 化学式或化学式列表，可包含通配符
- num_chunks: 最大数据块数量
- chunk_size: 每块数据条目数量
- all_fields: 是否返回文档所有字段
- fields: 返回指定字段
结果以 JSON 文件形式上传到 MinIO，并返回文件 URL。
""",
    args_schema=MPAbsorptionInput,
    metadata={"args_schema_json": MPAbsorptionInput.schema()}
)

# -----------------------------
# 工具13
# -----------------------------
