from pydantic import BaseModel, Field
from typing import Dict, Any

from rdkit import Chem
from rdkit.Chem import rdMolDescriptors
from workflow.tools.chemistry.utils import is_multiple_smiles, split_smiles,tanimoto,is_smiles, pubchem_query2smiles
from langchain_core.tools import StructuredTool
from workflow.const import Tools

from workflow.utils.minio_utils import upload_content_to_minio


# ------------------------------
# 1. 专利检索
# ------------------------------
# delete
# ------------------------------
# 2. 分子相似度计算
# ------------------------------
class MolSimilarityInput(BaseModel):
    compound_smiles_1: str = Field(
        ..., description="第一个分子的 SMILES 表达式，例如 'CCO'"
    )
    compound_smiles_2: str = Field(
        ..., description="第二个分子的 SMILES 表达式，例如 'CN'"
    )


async def mol_similarity_coroutine(
    compound_smiles_1: str,
    compound_smiles_2: str
) -> Dict[str, Any]:
    """
    输入两个分子的 SMILES 表达式，计算并返回它们的 Tanimoto 相似度及解释性描述。
    """
    try:
        similarity = tanimoto(compound_smiles_1, compound_smiles_2)

        if isinstance(similarity, str):
            return {"error": similarity}

        if similarity == 1:
            return {"error": "Input molecules are identical"}

        # 相似度等级映射
        sim_score = {
            0.9: "very similar",
            0.8: "similar",
            0.7: "somewhat similar",
            0.6: "not very similar",
            0: "not similar",
        }
        val = sim_score[max(k for k in sim_score.keys() if k <= round(similarity, 1))]

        return {
            "tanimoto_similarity": round(similarity, 4),
            "interpretation": f"The two molecules are {val}."
        }

    except Exception as e:
        return {"error": f"Tanimoto 相似度计算失败: {str(e)}"}


mol_similarity_tool = StructuredTool.from_function(
    coroutine=mol_similarity_coroutine,
    name=Tools.MolSimilarity,
    description="""
    【领域：化学】
    计算两个分子的 Tanimoto 相似度。
    功能:
      - 输入两个分子的 SMILES 表达式。
      - 返回数值化相似度 (0-1) 及自然语言解释。
    参数:
      - compound_smiles_1: 第一个分子 SMILES
      - compound_smiles_2: 第二个分子 SMILES
    输出:
      - tanimoto_similarity: 相似度数值 (float)
      - interpretation: 自然语言解释
    """,
    args_schema=MolSimilarityInput,
    metadata={"args_schema_json": MolSimilarityInput.schema()}
)


# ------------------------------
# 3. 分子量计算
# ------------------------------
class SMILES2WeightInput(BaseModel):
    compound_smiles: str = Field(
        ..., description="化合物的 SMILES 表达式，例如 'CCO'"
    )


async def smiles2weight_coroutine(
    compound_smiles: str
) -> Dict[str, Any]:
    """
    输入分子的 SMILES 表达式，计算并返回其分子量。
    """
    try:
        mol = Chem.MolFromSmiles(compound_smiles)
        if mol is None:
            return {"error": "Invalid SMILES string"}

        mol_weight = rdMolDescriptors.CalcExactMolWt(mol)
        return {"molecular_weight": mol_weight}

    except Exception as e:
        return {"error": f"分子量计算失败: {str(e)}"}


smiles2weight_tool = StructuredTool.from_function(
    coroutine=smiles2weight_coroutine,
    name=Tools.SMILES2Weight,
    description="""
    【领域：化学】
    根据 SMILES 表达式计算分子量。
    功能:
      - 输入化合物 SMILES。
      - 返回其精确分子量 (Exact Molecular Weight)。
    参数:
      - compound_smiles: 化合物 SMILES 字符串
    输出:
      - molecular_weight: 分子量 (float)
    """,
    args_schema=SMILES2WeightInput,
    metadata={"args_schema_json": SMILES2WeightInput.schema()}
)


# ------------------------------
# 4. 官能团识别
# ------------------------------
class FuncGroupsInput(BaseModel):
    compound_smiles: str = Field(
        ..., description="化合物的 SMILES 表达式，例如 'CCO'"
    )


async def func_groups_coroutine(
    compound_smiles: str
) -> Dict[str, Any]:
    """
    输入分子的 SMILES 表达式，识别并返回该分子所包含的常见官能团（功能基）。
    """
    dict_fgs = {
        "furan": "o1cccc1",
        "aldehydes": " [CX3H1](=O)[#6]",
        "esters": " [#6][CX3](=O)[OX2H0][#6]",
        "ketones": " [#6][CX3](=O)[#6]",
        "amides": " C(=O)-N",
        "thiol groups": " [SH]",
        "alcohol groups": " [OH]",
        "carboxylic acids": "*-C(=O)[O;D1]",
        "nitro": "*-[N;D3](=[O;D1])[O;D1]",
        "cyano": "*-[C;D2]#[N;D1]",
        "halogens": "*-[#9,#17,#35,#53]",
        "primary amines": "*-[N;D1]",
        "nitriles": "*#[N;D1]",
        # ... 可扩展
    }

    try:
        def _is_fg_in_mol(mol_smiles, fg):
            fgmol = Chem.MolFromSmarts(fg)
            mol = Chem.MolFromSmiles(mol_smiles.strip())
            return len(mol.GetSubstructMatches(fgmol, uniquify=True)) > 0

        detected_groups = [
            name for name, fg in dict_fgs.items()
            if _is_fg_in_mol(compound_smiles, fg)
        ]

        return {"functional_groups": detected_groups}

    except Exception as e:
        return {"error": f"官能团识别失败: {str(e)}"}


func_groups_tool = StructuredTool.from_function(
    coroutine=func_groups_coroutine,
    name=Tools.FuncGroups,
    description="""
    【领域：化学】
    识别分子中的常见官能团 (functional groups)。
    功能:
      - 输入分子的 SMILES 表达式。
      - 输出该分子所包含的官能团列表。
    参数:
      - compound_smiles: 化合物 SMILES 字符串
    输出:
      - functional_groups: 识别出的官能团列表 (List[str])
    """,
    args_schema=FuncGroupsInput,
    metadata={"args_schema_json": FuncGroupsInput.schema()}
)


# ------------------------------
# 5. 爆炸性检查
# ------------------------------
# delete


# ------------------------------
# 6. 受控化学品相似度检查
# ------------------------------
# delete

# ------------------------------
# 7. 受控化学品检查
# ------------------------------
# delete
