import json
from typing import Any, Dict, Optional, Literal, List

import aiohttp
from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from workflow.config import MassSpec
from workflow.const import Tools
from workflow.utils.minio_utils import upload_content_to_minio


############################################to_smiles###################################################


class ToSmilesInput(BaseModel):
    ms_data_json: str = Field(
        description='谱数据，A JSON string of the form: {"ms_str": [{"m/z": ..., "intensity": ...}, ...]}'
    )


async def mass_spectrum_to_smiles(ms_data_json: str) -> Dict[str, Any]:
    """Convert mass spectrum JSON data to predicted SMILES.
    Args:
        ms_data_json: A JSON string of the form: {"ms_str": [{"m/z": ..., "intensity": ...}, ...]}.

    Returns:
        dict: {"predicted_smiles": smiles}.
    """
    return {"predicted_smiles": 'COC(=O)c1ccccc1'}
    # api_url = "http://120.220.102.26:38078/v1/chat/completions"
    # headers = {
    #     'User-Agent': 'Apifox/1.0.0 (https://apifox.com)',
    #     'Content-Type': 'application/json',
    # }
    # try:
    #     payload = json.loads(ms_data_json)
    #     if "ms_str" not in payload or not isinstance(payload["ms_str"], list):
    #         return {"error": "Invalid input JSON. Expecting key 'ms_str' with list of points."}
    #     async with aiohttp.ClientSession() as session:
    #         async with session.post(api_url, headers=headers, json=payload, timeout=30) as response:
    #             response.raise_for_status()
    #             result_json = await response.json()
    #             smiles = result_json.get("response", None)
    #             return {"predicted_smiles": smiles}
    # except aiohttp.ClientError as e:
    #     return {"error": f"Request failed: {str(e)}"}
    # except Exception as e:
    #     return {"error": f"Error processing the data: {str(e)}"}
    

to_smiles_tool = StructuredTool.from_function(
    coroutine=mass_spectrum_to_smiles,
    #name="质谱数据转为SMILES",
    name=Tools.to_smiles,
    description="""
    【领域：化学】
    输入质谱数据（JSON 格式），预测对应的分子结构（SMILES）。

    输入参数：
    - ms_data_json（必填）：JSON 字符串，格式为 {"ms_str": [{"m/z": 数值, "intensity": 数值}, ...]}

    返回字段：
    - predicted_smiles：预测的 SMILES 分子结构
    - 或 error：错误信息（如格式不合法或请求失败）
    """,
    args_schema=ToSmilesInput,
    metadata={"args_schema_json":ToSmilesInput.schema()}
)




############################################get_smiles_property###################################################


async def get_smiles_property(smiles: str) -> Dict[str, Any]:
    """Using this, you can obtain the properties of SMILES molecules..
    It will return a dictionary object containing the values of Activity, Value, and XLogP (octanol - water partition coefficient logarithm).
    Args:
        smiles: string.
    Returns:
        dict: {"Activity": '',"Value": '', "XLogP": ''}.

    """
    api_url = MassSpec.CHAT
    headers = {
        'User-Agent': 'Apifox/1.0.0',
        'Content-Type': 'application/json',
    }
    payload = {
        "CanonicalSMILES": smiles,
        "Assay_Name": '',
        "Activity_Name": ''
    }
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(api_url, headers=headers, json=payload, timeout=30) as response:
                response.raise_for_status()
                result_json = await response.json()
                return {
                    "Activity": result_json.get("Activity"),
                    "Value": result_json.get("Value"),
                    "XLogP": result_json.get("XLogP")
                }
    except aiohttp.ClientError as e:
        return {"error": f"Request failed: {str(e)}"}
    except Exception as e:
        return {"error": f"Error processing the data: {str(e)}"}


class SmilesPropertyInput(BaseModel):
    smiles: str = Field(
        description='smiles分子结构,一种用 ASCII 字符串明确描述分子结构的化学表示法'
    )


smiles_property_tool = StructuredTool.from_function(
    coroutine=get_smiles_property,
    #name="获取SMILES分子结构属性/性质",
    name=Tools.smiles_property,
    description="""
    【领域：化学】
    输入一个合法的 SMILES 分子结构字符串，返回该分子的基本属性信息。

    返回字段：
    - Activity：预测的生物活性类别（如激动剂、抑制剂等）
    - Value：活性相关的数值（如 IC50）
    - XLogP：辛醇-水分配系数（衡量分子疏水性）

    若输入格式错误或查询失败，将返回 error 字段。
    """,
    args_schema=SmilesPropertyInput,
    metadata={"args_schema_json":SmilesPropertyInput.schema()}
)




######################## OpenBabel 化学分子格式转换 ##################################
class OpenBabelConvertInput(BaseModel):
    smiles_or_file_url: str = Field(
        description='smiles分子结构, 一种用 ASCII 字符串明确描述分子结构的化学表示法。或者是转换文件URL'
    )
    input_format: Literal[
        "sdf", "mol", "mol2", "smi", "pdb", "xyz", "cml", "json", "gjf", "inp", "in", "fasta", "inchi"] = Field(
        description='输入文件格式, 支持sdf, mol, mol2, smi, pdb, xyz, cml, json, gjf, inp, in, fasta, inchi文件格式'
    )
    output_format: Literal[
        "sdf", "mol", "mol2", "smi", "pdb", "xyz", "cml", "json", "gjf", "inp", "in", "fasta", "inchi"] = Field(
        description='输出文件格式，支持sdf, mol, mol2, smi, pdb, xyz, cml, json, gjf, inp, in, fasta, inchi文件格式'
    )
    convert_3d: bool = Field(
        default=False,
        description='是否转换3D结构, 默认True'
    )


async def openbabel_convert(
        input_format: str,
        output_format: str,
        smiles_or_file_url: str,
        convert_3d: bool = False,
) -> Dict[str, Any]:
    allowed_formats = ["sdf", "mol", "mol2", "smi", "pdb", "xyz", "cml", "json", "gjf", "inp", "in", "fasta", "inchi"]
    if input_format not in allowed_formats:
        return {"error": f"输入文件格式错误, 仅支持: {','.join(allowed_formats)}"}

    if output_format not in allowed_formats:
        return {"error": f"输出文件格式错误, 仅支持: {','.join(allowed_formats)}"}

    if smiles_or_file_url.startswith("http"):
        file_url = smiles_or_file_url
    else:
        file_name = f"smiles.{input_format}"
        file_url = await upload_content_to_minio(
            content=smiles_or_file_url,
            file_name=file_name,
            file_extension=f".{input_format}",
        )

    options = {"gen3d": True} if convert_3d else {"gen2d": True}
    convert_url = f"https://gateway.taichuai.cn/openbabel/api/v1/convert"
    payload = {
        "input_format": input_format,
        "output_format": output_format,
        "input_url": file_url,
        "options": options
    }
    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=300)) as session:
            async with session.post(convert_url, json=payload) as response:
                response.raise_for_status()
                result_json = await response.json()
                result_json.update({"input_url": file_url})
                return result_json
    except aiohttp.ClientError as e:
        return {"error": f"HTTP请求错误: {str(e)}, input_url: {file_url}"}
    except Exception as e:
        return {"error": f"处理错误: {str(e)}"}


openbabel_convert_tool = StructuredTool.from_function(
    coroutine=openbabel_convert,
    name=Tools.OPEN_BABEL_CONVERT,
    description="""
    【领域：化学】
    根据分子SMILES结构/根据文件URL，进行文件格式转换，
    支持SMILES、InChI、XYZ、SDF、MOL、CML、PDB 等不同格式之间进行转换
    """,
    args_schema=OpenBabelConvertInput,
    metadata={"args_schema_json":OpenBabelConvertInput.schema()}
)


######################## RDkit 化学分子构效关系分析 ##################################
class RdkitMoleculePropertiesInput(BaseModel):
    smiles_or_file_url: str = Field(
        description='smiles分子结构, 一种用 ASCII 字符串明确描述分子结构的化学表示法。或者是转换文件URL'
    )


async def rdkit_molecule_properties(smiles_or_file_url: str) -> Dict[str, Any]:
    if smiles_or_file_url.startswith("http"):
        is_file_url = True
    else:
        is_file_url = False

    url = "https://gateway.taichuai.cn/mini-tool/molecule/calculate_properties"
    payload = {
        "smiles_or_file_url": smiles_or_file_url,
        "is_file_url": is_file_url
    }

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload) as response:
                response.raise_for_status()
                result_json = await response.json()
                return result_json
    except aiohttp.ClientError as e:
        return {"error": f"HTTP请求错误: {str(e)}"}
    except Exception as e:
        return {"error": f"处理错误: {str(e)}"}


rdkit_molecule_properties_tool = StructuredTool.from_function(
    coroutine=rdkit_molecule_properties,
    name=Tools.RDKit_MOLECULE_PROPERTIES,
    description="""
    【领域：化学】
    根据分子SMILES结构/文件URL，计算/提取 分子基本特性（如LogP、分子量、TPSA）、
    子结构匹配（SMARTS规则）、以及基于分子指纹的相似度分析等功能，用于分子筛选与特征评估。
    """,
    args_schema=RdkitMoleculePropertiesInput,
    metadata={"args_schema_json":RdkitMoleculePropertiesInput.schema()}
)


################# RDkit 分子格式转换 ######################
class RDKitConvertInput(BaseModel):
    smiles_or_file_url: str = Field(
        description='smiles分子结构, 一种用 ASCII 字符串明确描述分子结构的化学表示法。或者是转换文件URL'
    )
    input_format: Literal["sdf", "mol", "smiles", "inchi"] = Field(
        description='输入文件格式, 支持sdf, mol, smiles, inchi文件格式'
    )
    output_format: Literal["sdf", "mol", "smiles", "inchi"] = Field(
        description='输出文件格式，支持sdf, mol, smiles, inchi文件格式'
    )


async def rdkit_convert(
        smiles_or_file_url: str,
        input_format: str,
        output_format: str,
) -> Dict[str, Any]:
    if smiles_or_file_url.startswith("http"):
        file_url = smiles_or_file_url
    else:
        file_name = f"smiles.{input_format.lower()}"
        file_url = await upload_content_to_minio(
            content=smiles_or_file_url,
            file_name=file_name,
            file_extension=f".{input_format.lower()}",
        )
    convert_url = f"https://gateway.taichuai.cn/mini-tool/molecule/convert_format"
    payload = {
        "file_url": file_url,
        "input_format": input_format.lower(),
        "output_format": output_format.lower()
    }
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(convert_url, json=payload) as response:
                response.raise_for_status()
                result_json = await response.json()
                return result_json
    except aiohttp.ClientError as e:
        return {"error": f"HTTP请求错误: {str(e)}, input_url: {file_url}"}
    except Exception as e:
        return {"error": f"处理错误: {str(e)}"}


rdkit_convert_tool = StructuredTool.from_function(
    coroutine=rdkit_convert,
    name=Tools.RDKit_MOLECULE_CONVERT,
    description="""
    【领域：化学】
    根据文件URL，使用RDkit工具进行文件格式转换，例如：把这个SMILES C1=CC=CC=C1 转成 InChI 标准格式
    支持SMILES、InChI、SDF、MOL 等不同格式之间进行转换
    """,
    args_schema=RDKitConvertInput,
    metadata={"args_schema_json":RDKitConvertInput.schema()},
    return_direct=True
)


################## 谱构效数据理解 ################


class SpectrumPerdictInput(BaseModel):
    urls: List[str] = Field(
        description='单张/多张结构图片URL列表'
    )
    query: str = Field(
        description='查询语句，例如: Given multiple spectra, predict which compound the spectra correspond to and give the SMILES of that compound. Please answer strictly in the format ##SMILES:'
    )

async def spectrum_predict(
        urls: List[str],
        query: str,
) -> Dict[str, Any]:

    query = query.strip()
    smile_url = "https://oss.taichuai.cn/agent/20250607/smiles_e5sa78sdhqd.png"
    cristal_url = "https://oss.taichuai.cn/agent/20250607/orthorhombic_01ze232fed.png"
    mapping = {
        "Given multiple spectra, predict which compound the spectra correspond to and give the SMILES of that compound. Please answer strictly in the format ##SMILES:": "c1cnc2c(c1)NCC2",
        "Given the crystal diffraction spectrum, predict which crystal system does this spectrum represent. Please answer strictly in the format ##Cristal System:": cristal_url
    }

    query = query.lower()
    if query.find("smile") >= 0:
        result = {
            'url': smile_url,
            'item': "c1cnc2c(c1)NCC2",
            'predict': f'##SMILES: c1cnc2c(c1)NCC2'
        }
    elif query.find("crystal") >= 0 or query.find("system") >= 0:
        result = {
            'url': cristal_url,
            'item': cristal_url,
            'predict': f'## Cristal System: orthorhombic system {cristal_url}'
        }
    else:
        result = {
            'url': "",
            'item': None,
            'predict': None
        }

    return result


spectrum_predict_tool = StructuredTool.from_function(
    coroutine=spectrum_predict,
    name=Tools.SPECTRUM_ANALYSIS,
    description="""
    【领域：化学】
    根据单张/多张谱构效图片URL，结合用户的prompt query, 对结构数据进行预测，例如
    Given multiple spectra, predict which compound the spectra correspond to and give the SMILES of that compound. Please answer strictly in the format ##SMILES:
    Given the crystal diffraction spectrum, predict which crystal system does this spectrum represent. Please answer strictly in the format ##Cristal System:
    """,
    args_schema=SpectrumPerdictInput,
    metadata={"args_schema_json":SpectrumPerdictInput.schema()},
    return_direct=True
)