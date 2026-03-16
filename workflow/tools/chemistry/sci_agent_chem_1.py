from typing import Dict, Any
from pydantic import BaseModel, Field
from langchain_core.tools import StructuredTool
from rdkit import Chem
from rdkit.Chem import rdMolDescriptors, DataStructs
from rdkit.Chem.rdinchi import MolToInchi
from workflow.tools.chemistry.sci_agent_utils  import send_chemspider_request

from pydantic import BaseModel, Field
from typing import Dict, Any

from workflow.tools.chemistry.utils import is_multiple_smiles, split_smiles,tanimoto,is_smiles, pubchem_query2smiles
from langchain_core.tools import StructuredTool
from workflow.const import Tools
from workflow.utils.minio_utils import upload_content_to_minio
from rdkit.Chem import Draw, rdTautomerQuery
import logging
import base64
from workflow.utils.minio_utils import upload_content_to_minio
from datetime import datetime, timedelta
from Bio import Entrez, SeqIO
from io import BytesIO, StringIO
from minio.error import S3Error


import numpy as np






# 2. 计算分子式 ---------------------------------------------------

class CalculateMolFormulaInput(BaseModel):
    smiles: str = Field(
        ..., description="分子的 SMILES 字符串，例如 'CCO'（乙醇）"
    )

async def calculate_MolFormula_coroutine(smiles: str) -> Dict[str, Any]:
    """
    根据 SMILES 计算分子式。
    """
    try:
        smiles = smiles.replace(" ", "").replace("\n", "").replace("'", "").replace('"', "")
        mol = Chem.MolFromSmiles(smiles)
        if mol is None:
            raise ValueError("无效的 SMILES 字符串")
        mol_formula = rdMolDescriptors.CalcMolFormula(mol)
        return {"input_smiles": smiles, "molecular_formula": mol_formula}
    except Exception as e:
        return {"error": f"分子式计算失败: {str(e)}"}

calculate_MolFormula_tool = StructuredTool.from_function(
    coroutine=calculate_MolFormula_coroutine,
    name=Tools.CALCULATE_MOL_FORMULA,
    description="""
    【领域：化学】
    根据分子的 SMILES 字符串，计算分子式。
    返回：
      - input_smiles: 输入的 SMILES
      - molecular_formula: 计算得到的分子式
    """,
    args_schema=CalculateMolFormulaInput,
    metadata={"args_schema_json": CalculateMolFormulaInput.schema()}
)


# 3. SMILES -> InChI ---------------------------------------------------

class ConvertSMILESToInChIInput(BaseModel):
    smiles: str = Field(
        ..., description="分子的 SMILES 字符串，例如 'CCO'（乙醇）"
    )

async def convert_smiles_to_inchi_coroutine(smiles: str) -> Dict[str, Any]:
    """
    将 SMILES 转换为 InChI。
    """
    try:
        mol = Chem.MolFromSmiles(smiles)
        if not mol:
            return {"error": "无效的 SMILES 字符串"}
        inchi = MolToInchi(mol)
        return {"smiles": smiles, "inchi": inchi}
    except Exception as e:
        return {"error": f"SMILES 转 InChI 失败: {str(e)}"}

convert_smiles_to_inchi_tool = StructuredTool.from_function(
    coroutine=convert_smiles_to_inchi_coroutine,
    name=Tools.CONVERT_SMILES_TO_INCHI,
    description="""
    【领域：化学】
    将分子的 SMILES 转换为 InChI 表达式。
    返回：
      - smiles: 输入的 SMILES
      - inchi: 转换得到的 InChI
    """,
    args_schema=ConvertSMILESToInChIInput,
    metadata={"args_schema_json": ConvertSMILESToInChIInput.schema()}
)


# 9. showmol ---------------------------------------------------
# 输入参数
class ShowMolInput(BaseModel):
    smiles: str = Field(..., description="分子的 SMILES 表达式，例如 'CCO'")


# 协程实现
async def show_mol_coroutine(smiles: str) -> Dict[str, Any]:
    """
    根据 SMILES 生成分子图像 (PNG)，上传到 MinIO 并返回文件 URL。
    """
    try:
        if not isinstance(smiles, str):
            raise ValueError("SMILES 必须是字符串")

        mol = Chem.MolFromSmiles(smiles)
        if mol is None:
            raise ValueError("无效的 SMILES")

        # 生成 PNG 图像并写入 buffer
        img = Draw.MolToImage(mol, size=(300, 300))
        buffer = BytesIO()
        img.save(buffer, format="PNG")
        buffer.seek(0)
        data = buffer.getvalue()

        # 构造文件名
        now = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename_base = f"molecule_{now}"
        file_name = f"{filename_base}.png"

        # 上传到 MinIO
        file_url = await upload_content_to_minio(
            content=data,
            file_name=file_name,
            file_extension=".png",
            content_type="image/png",
            no_expired=True,
        )
        return {"molecule_image_url": file_url, "smiles": smiles}

    except S3Error as e:
        return {"error": f"MinIO 上传失败: {e.code} - {e.message}"}
    except Exception as e:
        return {"error": f"分子图像生成失败: {str(e)}"}


# 工具定义
show_mol_tool = StructuredTool.from_function(
    coroutine=show_mol_coroutine,
    name=Tools.SHOW_MOL,
    description="""
    【领域：化学】
    根据 SMILES 生成分子结构图像 (PNG)，上传到 MinIO 并返回文件 URL。
    返回：
      - molecule_image_url: 生成的分子图像 URL
      - smiles: 输入的 SMILES
    """,
    args_schema=ShowMolInput,
    metadata={"args_schema_json": ShowMolInput.schema()}
)

# 10. Add Hydrogens  ---------------------------------------------------
class AddHydrogensInput(BaseModel):
    smiles: str = Field(
        ..., description="输入分子 SMILES 字符串，例如 'CCO'。请直接输入 SMILES，不要包含其他字符。"
    )

async def add_hydrogens_coroutine(smiles: str) -> Dict[str, Any]:
    """
    对分子 SMILES 添加氢原子。
    返回 Markdown 格式的输入/输出 SMILES。
    """
    try:
        smiles_clean = smiles.replace(' ', '').replace('\n', '').replace('\'', '').replace('\"', '').replace('.','')
        if 'smiles=' in smiles_clean:
            _, smiles_clean = smiles_clean.split('=')
        mol = Chem.MolFromSmiles(smiles_clean)
        if mol is None:
            raise ValueError("Invalid SMILES string.")
        mol_h = Chem.AddHs(mol)
        markdown = f'''## Add Hydrogens
**Input SMILES:** {smiles_clean}
**Output SMILES:** {Chem.MolToSmiles(mol_h)}
'''
        return {"markdown": markdown}
    except Exception as e:
        return {"error": f"Add Hydrogens failed: {str(e)}"}

add_hydrogens_tool = StructuredTool.from_function(
    coroutine=add_hydrogens_coroutine,
    name=Tools.ADD_HYDROGENS,
    description="""
    【领域：化学】
    对分子 SMILES 添加氢原子。
    返回 Markdown 格式字符串，包含输入 SMILES 和添加氢原子后的输出 SMILES。
    """,
    args_schema=AddHydrogensInput,
    metadata={"args_schema_json": AddHydrogensInput.schema()}
)


# 11. Remove Hydrogens  ---------------------------------------------------
class RemoveHydrogensInput(BaseModel):
    smiles: str = Field(
        ..., description="输入分子 SMILES 字符串，例如 'CCO'。请直接输入 SMILES，不要包含其他字符。"
    )

async def remove_hydrogens_coroutine(smiles: str) -> Dict[str, Any]:
    """
    从分子 SMILES 中移除氢原子。
    返回 Markdown 格式的输入/输出 SMILES。
    """
    try:
        smiles_clean = smiles.replace(' ', '').replace('\n', '').replace('\'', '').replace('\"', '').replace('.','')
        if 'smiles=' in smiles_clean:
            _, smiles_clean = smiles_clean.split('=')
        mol = Chem.MolFromSmiles(smiles_clean)
        if mol is None:
            raise ValueError("Invalid SMILES string.")
        mol_no_h = Chem.RemoveHs(mol)
        markdown = f'''## Remove Hydrogens
**Input SMILES:** {smiles_clean}
**Output SMILES:** {Chem.MolToSmiles(mol_no_h)}
'''
        return {"markdown": markdown}
    except Exception as e:
        return {"error": f"Remove Hydrogens failed: {str(e)}"}

remove_hydrogens_tool = StructuredTool.from_function(
    coroutine=remove_hydrogens_coroutine,
    name=Tools.REMOVE_HYDROGENS,
    description="""
    【领域：化学】
    从分子 SMILES 中移除氢原子。
    返回 Markdown 格式字符串，包含输入 SMILES 和移除氢原子后的输出 SMILES。
    """,
    args_schema=RemoveHydrogensInput,
    metadata={"args_schema_json": RemoveHydrogensInput.schema()}
)


# 12. Kekulize  ---------------------------------------------------
class KekulizeInput(BaseModel):
    smiles: str = Field(
        ..., description="输入分子 SMILES 字符串，例如 'c1ccccc1'。请直接输入 SMILES，不要包含其他字符。"
    )

async def kekulize_coroutine(smiles: str) -> Dict[str, Any]:
    """
    对分子进行 Kekulization 转换，将芳香键转为交替单/双键。
    返回 Markdown 格式的输入/输出 SMILES。
    """
    try:
        smiles_clean = smiles.replace(' ', '').replace('\n', '').replace('\'', '').replace('\"', '').replace('.','')
        if 'smiles=' in smiles_clean:
            _, smiles_clean = smiles_clean.split('=')
        mol = Chem.MolFromSmiles(smiles_clean)
        if mol is None:
            raise ValueError("Invalid SMILES string.")
        Chem.Kekulize(mol)
        markdown = f'''## Kekulize
**Input SMILES:** {smiles_clean}
**Output SMILES:** {Chem.MolToSmiles(mol)}
'''
        return {"markdown": markdown}
    except Exception as e:
        return {"error": f"Kekulize failed: {str(e)}"}

kekulize_tool = StructuredTool.from_function(
    coroutine=kekulize_coroutine,
    name=Tools.KEKULIZE,
    description="""
    【领域：化学】
    对分子进行 Kekulization 转换，将芳香键转为交替单/双键。
    返回 Markdown 格式字符串，包含输入 SMILES 和 Kekulize 后的输出 SMILES。
    """,
    args_schema=KekulizeInput,
    metadata={"args_schema_json": KekulizeInput.schema()}
)

# 13. Set Aromaticity  ---------------------------------------------------
class SetAromaticityInput(BaseModel):
    smiles: str = Field(
        ..., description="输入分子 SMILES 字符串，例如 'c1ccccc1'。请直接输入 SMILES，不要包含其他字符。"
    )

async def set_aromaticity_coroutine(smiles: str) -> Dict[str, Any]:
    """
    对分子进行芳香性感知操作。
    返回 Markdown 格式的输入/输出 SMILES。
    """
    try:
        smiles_clean = smiles.replace(' ', '').replace('\n', '').replace('\'', '').replace('\"', '').replace('.','')
        if 'smiles=' in smiles_clean:
            _, smiles_clean = smiles_clean.split('=')
        mol = Chem.MolFromSmiles(smiles_clean)
        if mol is None:
            raise ValueError("Invalid SMILES string.")
        Chem.SetAromaticity(mol)
        markdown = f'''## Set Aromaticity
**Input SMILES:** {smiles_clean}
**Output SMILES:** {Chem.MolToSmiles(mol)}
'''
        return {"markdown": markdown}
    except Exception as e:
        return {"error": f"Set Aromaticity failed: {str(e)}"}

set_aromaticity_tool = StructuredTool.from_function(
    coroutine=set_aromaticity_coroutine,
    name=Tools.SET_AROMATICITY,
    description="""
    【领域：化学】
    对分子进行芳香性感知操作。
    返回 Markdown 格式字符串，包含输入 SMILES 和处理后的输出 SMILES。
    """,
    args_schema=SetAromaticityInput,
    metadata={"args_schema_json": SetAromaticityInput.schema()}
)


# 14. Pattern Fingerprint  ---------------------------------------------------
class PatternFingerprintInput(BaseModel):
    smiles: str = Field(
        ..., description="输入分子的 SMILES 字符串，例如 'CCO'。请直接输入 SMILES，无需其他字符。"
    )

async def pattern_fingerprint_coroutine(smiles: str) -> Dict[str, Any]:
    """
    生成分子的 Pattern Fingerprint（基于 SMARTS 子结构模式的比特向量）。
    
    返回：
      - NumBits: 指纹总长度
      - NumOnBits: 打开的比特数
      - BitVector: 字符串形式的比特向量
      - Binary: 二进制字符串
    """
    try:
        smiles = smiles.replace(" ", "").replace("\n", "").replace("\'", "").replace("\"", "").replace(".","")
        mol = Chem.MolFromSmiles(smiles)
        if mol is None:
            raise ValueError("无效的 SMILES 字符串。")

        result = rdTautomerQuery.PatternFingerprintTautomerTarget(mol)

        markdown = f'''
## Pattern Fingerprint Result

**NumBits:** {result.GetNumBits()}
**NumOnBits:** {result.GetNumOnBits()}
**BitVector:** {result.ToBitString()}
**Binary:** {result.ToBinary()}
'''
        return {"fingerprint_markdown": markdown}
    except Exception as e:
        return {"error": f"Pattern Fingerprint 生成失败: {str(e)}"}

pattern_fingerprint_tool = StructuredTool.from_function(
    coroutine=pattern_fingerprint_coroutine,
    name=Tools.PATTERN_FINGERPRINT,
    description="""
    【领域：化学】
生成分子的 Pattern Fingerprint。
输入 SMILES 字符串，返回基于 SMARTS 模式的比特向量信息，包括：
- 总比特数 NumBits
- 打开比特数 NumOnBits
- 字符串形式 BitVector
- 二进制形式 Binary
""",
    args_schema=PatternFingerprintInput,
    metadata={"args_schema_json": PatternFingerprintInput.schema()}
)

# 15. Morgan Fingerprint  ---------------------------------------------------
class MorganFingerprintInput(BaseModel):
    smiles: str = Field(
        ..., description="输入分子的 SMILES 字符串，例如 'CCO'。请直接输入 SMILES，无需其他字符。"
    )

async def morgan_fingerprint_coroutine(smiles: str) -> Dict[str, Any]:
    """
    生成分子的 Morgan Fingerprint（局部环境编码的比特向量）。
    
    返回：
      - input_smiles: 原始 SMILES
      - morgan_fingerprint: numpy 数组形式的 Morgan 指纹
    """
    try:
        smiles = smiles.replace(' ', '').replace('\n', '').replace('\'', '').replace('\"', '').replace('.','')
        mol = Chem.MolFromSmiles(smiles)
        if mol is None:
            raise ValueError("无效的 SMILES 字符串。")

        fingerprint = rdMolDescriptors.GetMorganFingerprintAsBitVect(mol, 2)
        numpy_array = np.zeros((fingerprint.GetNumBits(),), dtype=int)
        DataStructs.ConvertToNumpyArray(fingerprint, numpy_array)

        markdown = f'''
## Morgan Fingerprint Result
**Input SMILES:** {smiles}
**Morgan Fingerprint:** {numpy_array.tolist()}
'''
        return {"fingerprint_markdown": markdown}
    except Exception as e:
        return {"error": f"Morgan Fingerprint 生成失败: {str(e)}"}

morgan_fingerprint_tool = StructuredTool.from_function(
    coroutine=morgan_fingerprint_coroutine,
    name=Tools.MORGAN_FINGERPRINT,
    description="""
    【领域：化学】
生成分子的 Morgan Fingerprint（局部化学环境编码的比特向量）。
输入 SMILES 字符串，返回：
- 原始 SMILES
- Morgan 指纹（numpy 数组形式）
""",
    args_schema=MorganFingerprintInput,
    metadata={"args_schema_json": MorganFingerprintInput.schema()}
)

# 16. RDKit Fingerprint  ---------------------------------------------------
class RDKitFingerprintInput(BaseModel):
    smiles: str = Field(
        ..., description="输入分子的 SMILES 字符串，例如 'CCO'。请直接输入 SMILES，无需其他字符。"
    )

async def rdkit_fingerprint_coroutine(smiles: str) -> Dict[str, Any]:
    """
    生成分子的 RDKit 指纹（基于 RDKit 的哈希指纹）。
    
    返回：
      - input_smiles: 原始 SMILES
      - rdkit_fingerprint: 二进制字符串形式
    """
    try:
        mol = Chem.MolFromSmiles(smiles)
        if mol is None:
            raise ValueError("无效的 SMILES 字符串。")

        fp = Chem.RDKFingerprint(mol, nBitsPerHash=1)
        binary_fp = fp.ToBitString()

        markdown = f'''
## RDKit Fingerprint Result
**Input SMILES:** {smiles}
**RDKit Fingerprint:** {binary_fp}
'''
        return {"fingerprint_markdown": markdown}
    except Exception as e:
        return {"error": f"RDKit Fingerprint 生成失败: {str(e)}"}

rdkit_fingerprint_tool = StructuredTool.from_function(
    coroutine=rdkit_fingerprint_coroutine,
    name=Tools.RDKIT_FINGERPRINT,
    description="""
    【领域：化学】
生成分子的 RDKit 指纹（基于 RDKit 哈希算法）。
输入 SMILES 字符串，返回：
- 原始 SMILES
- RDKit 指纹（二进制字符串形式）
""",
    args_schema=RDKitFingerprintInput,
    metadata={"args_schema_json": RDKitFingerprintInput.schema()}
)
