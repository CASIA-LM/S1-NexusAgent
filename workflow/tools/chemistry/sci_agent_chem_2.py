
from langchain_core.tools import StructuredTool

import asyncio
from workflow.tools.chemistry.utils import is_multiple_smiles, split_smiles,tanimoto,is_smiles, pubchem_query2smiles
from langchain_core.tools import StructuredTool
from workflow.const import Tools

from workflow.utils.minio_utils import upload_content_to_minio
from rdkit.Chem import Draw, rdTautomerQuery
import logging
import base64
from rdkit.Chem.Fingerprints.FingerprintMols import  FoldFingerprintToTargetDensity
from workflow.utils.minio_utils import upload_content_to_minio


from rdkit.Chem.Fingerprints import FingerprintMols
from rdkit.DataStructs.cDataStructs import ExplicitBitVect
from io import BytesIO
from datetime import datetime
from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
import numpy as np
from rdkit import Chem, DataStructs
from rdkit.Chem import AllChem, rdMolDescriptors
import logging
import time
import requests
from rdkit import Chem, DataStructs
from rdkit.Chem import AllChem, rdMolDescriptors



from .sci_agent_utils import *

def collect_reactions(tree):
    reactions = []
    if 'children' in tree and tree['children']:
        reaction_smarts = '{}>>{}'.format(
            '.'.join([node['smiles'] for node in tree['children']]),
            tree['smiles']
        )
        reactions.append(reaction_smarts)
    for node in tree['children']:
        reactions.extend(collect_reactions(node))
    return reactions

# ========== 1. 形状相似性计算工具 ==========
class CalculateShapeSimilarityInput(BaseModel):
    smiles_list: List[str] = Field(
        ..., description="分子 SMILES 字符串列表，例如 ['CCO', 'c1ccccc1']"
    )

async def calculate_shape_similarity_coroutine(
    smiles_list: List[str],
) -> Dict[str, Any]:
    """
    基于 USRCAT 描述符计算分子列表的形状相似性。
    返回 Markdown 格式的分子索引和相似性得分。
    """
    try:
        mols3d = []
        for smi in smiles_list:
            mol = Chem.MolFromSmiles(smi)
            if mol is None:
                raise ValueError(f"Invalid SMILES string: {smi}")
            m2 = Chem.AddHs(mol)
            if AllChem.EmbedMolecule(m2) != 0 or AllChem.MMFFOptimizeMolecule(m2, maxIters=2000) != 0:
                raise ValueError(f"Could not generate 3D conformation for molecule: {smi}")
            mols3d.append(m2)

        usrcats = [rdMolDescriptors.GetUSRCAT(mol) for mol in mols3d]

        markdown_output = "### Molecules and Their Indices\n\n"
        for idx, smi in enumerate(smiles_list):
            markdown_output += f"- Index {idx}: `{smi}`\n"

        markdown_output += "\n### Shape Similarity Scores (USRCAT)\n\n"
        for i in range(len(usrcats)):
            for j in range(i + 1, len(usrcats)):
                score = rdMolDescriptors.GetUSRScore(usrcats[i], usrcats[j])
                markdown_output += f"- Pair ({i}, {j}): USRCAT Score = {score:.4f}\n"

        return {"result_markdown": markdown_output}
    except Exception as e:
        return {"error": f"An error occurred while calculating shape similarity: {e}"}


calculate_shape_similarity_tool = StructuredTool.from_function(
    coroutine=calculate_shape_similarity_coroutine,
    name=Tools.calculate_shape_similarity,
    description="""
    【领域：化学】
    基于 USRCAT 描述符计算分子形状相似性。
    输入：SMILES 字符串列表
    输出：Markdown 格式的分子索引与成对 USRCAT 相似性分数。
    """,
    args_schema=CalculateShapeSimilarityInput,
    metadata={"args_schema_json": CalculateShapeSimilarityInput.schema()},
)

# ========== 2. 距离矩阵计算工具 ==========
class CalculateDistanceMatrixInput(BaseModel):
    smiles_list: List[str] = Field(
        ..., description="分子 SMILES 字符串列表，例如 ['CCO', 'CCN', 'c1ccccc1']"
    )

async def calculate_distance_matrix_coroutine(
    smiles_list: List[str],
) -> Dict[str, Any]:
    """
    基于分子指纹计算距离矩阵 (Tanimoto)。
    返回 Markdown 格式的矩阵表格。
    """
    try:
        data = []
        for smi in smiles_list:
            mol = Chem.MolFromSmiles(smi)
            if mol is None:
                raise ValueError(f"Invalid SMILES string: {smi}")
            fp = AllChem.GetMorganFingerprintAsBitVect(mol, radius=2)
            data.append((smi, fp))

        nPts = len(data)
        distsMatrix = np.zeros((nPts * (nPts - 1) // 2), dtype=np.float64)
        idx = 0
        for i in range(nPts):
            for j in range(i):
                distsMatrix[idx] = 1.0 - DataStructs.FingerprintSimilarity(data[i][1], data[j][1])
                idx += 1

        markdown_output = "### Molecules and Their Indices\n\n"
        for idx, smi in enumerate(smiles_list):
            markdown_output += f"- Mol {idx+1}: `{smi}`\n"

        markdown_output += "\n### Distance Matrix\n\n"
        markdown_output += "|   | " + " | ".join([f"Mol {i+1}" for i in range(nPts)]) + " |\n"
        markdown_output += "|---" * (nPts + 1) + "|\n"

        idx = 0
        for i in range(nPts):
            row = []
            for j in range(nPts):
                if i == j:
                    row.append("-")
                elif i < j:
                    row.append(f"{distsMatrix[idx]:.4f}")
                    idx += 1
                else:
                    row.append("")
            markdown_output += f"| Mol {i+1} | " + " | ".join(row) + " |\n"

        return {"result_markdown": markdown_output}
    except Exception as e:
        return {"error": f"An error occurred while calculating the distance matrix: {e}"}


calculate_distance_matrix_tool = StructuredTool.from_function(
    coroutine=calculate_distance_matrix_coroutine,
    name=Tools.calculate_distance_matrix,
    description="""
    【领域：化学】
    基于分子指纹 (Morgan Fingerprint) 计算 Tanimoto 距离矩阵。
    输入：SMILES 字符串列表
    输出：Markdown 格式的分子索引及距离矩阵表格。
    """,
    args_schema=CalculateDistanceMatrixInput,
    metadata={"args_schema_json": CalculateDistanceMatrixInput.schema()},
)

# ========== 3. 分子聚类工具 ==========
class ClusterMoleculesInput(BaseModel):
    smiles_list: List[str] = Field(
        ..., description="分子 SMILES 字符串列表，例如 ['CCO', 'CCN', 'c1ccccc1']"
    )
    algorithm_id: Optional[int] = Field(
        0, description="聚类算法 ID (默认 0，可选值依赖 RDKit 聚类模块，例如 WARDS)"
    )

async def cluster_molecules_coroutine(
    smiles_list: List[str],
    algorithm_id: Optional[int] = 0,
) -> Dict[str, Any]:
    """
    基于分子指纹进行聚类，返回聚类结果 Markdown。
    """
    try:
        data = []
        for smi in smiles_list:
            mol = Chem.MolFromSmiles(smi)
            if mol is None:
                raise ValueError(f"Invalid SMILES string: {smi}")
            fp = AllChem.GetMorganFingerprintAsBitVect(mol, radius=2)
            data.append((smi, fp))

        # RDKit clustering
        from rdkit.ML.Cluster import Butina
        dists = []
        for i in range(1, len(data)):
            sims = [1.0 - DataStructs.FingerprintSimilarity(data[i][1], data[j][1]) for j in range(i)]
            dists.extend(sims)
        clusters = Butina.ClusterData(dists, len(data), len(data), isDistData=True)

        markdown_output = "### Clustering Results\n\n"
        markdown_output += f"Total number of clusters: {len(clusters)}\n\n"
        for idx, cluster in enumerate(clusters):
            markdown_output += f"- Cluster {idx+1}: " + ", ".join([data[i][0] for i in cluster]) + "\n"

        return {"result_markdown": markdown_output}
    except Exception as e:
        return {"error": f"An error occurred while clustering molecules: {e}"}


cluster_molecules_tool = StructuredTool.from_function(
    coroutine=cluster_molecules_coroutine,
    name=Tools.cluster_molecules,
    description="""
    【领域：化学】
    基于分子指纹 (Morgan Fingerprint) 对分子进行聚类。
    输入：SMILES 字符串列表，可选聚类算法 ID
    输出：Markdown 格式的聚类结果，包括聚类数量及每个簇的分子成员。
    """,
    args_schema=ClusterMoleculesInput,
    metadata={"args_schema_json": ClusterMoleculesInput.schema()},
)

# -------------------------------
# Tool 1: 反应预测
# -------------------------------
# class PredictReactionInput(BaseModel):
#     reactants: str = Field(
#         ..., 
#         description="反应物的 SMILES 字符串，用 '.' 分隔多个反应物，例如 'CCO.CN'。"
#     )

# async def predict_reaction_coroutine(reactants: str) -> Dict[str, Any]:
#     """
#     基于 IBM RXN 平台预测给定反应物的反应结果，返回预测产物及详细说明。
#     """
#     try:
#         if not is_smiles(reactants):
#             return {"error": "输入格式错误：必须为有效的 SMILES 字符串。"}

#         while True:
#             await asyncio.sleep(2)
#             response = rxn4chem.predict_reaction(reactants)
#             if "prediction_id" in response.keys():
#                 break

#         while True:
#             await asyncio.sleep(2)
#             results = rxn4chem.get_predict_reaction_results(response["prediction_id"])
#             if "payload" in results["response"].keys():
#                 break

#         res_dict = results["response"]["payload"]["attempts"][0]
#         product = res_dict["productMolecule"]["smiles"]

#         markdown_result = f"""
# ### Reaction Prediction

# #### Reactants
# - **Reactants**: `{reactants}`

# #### Predicted Product
# - **Product**: `{product}`

# #### More Information
# - [IBM RXN for Chemistry](https://rxn.res.ibm.com)
# """
#         return {"markdown": markdown_result, "product_smiles": product}

#     except Exception as e:
#         return {"error": f"反应预测失败: {str(e)}"}

# predict_reaction_tool = StructuredTool.from_function(
#     coroutine=predict_reaction_coroutine,
#     name=Tools.PREDICT_REACTION,
#     description="""
#    【领域：化学】
#     基于 IBM RXN 平台预测化学反应结果。
#     输入反应物 SMILES 字符串（用 '.' 分隔），返回预测产物及详细 Markdown 格式说明。
#     """,
#     args_schema=PredictReactionInput,
#     metadata={"args_schema_json": PredictReactionInput.schema()} 
# )


# -------------------------------
# Tool 2: 逆合成路径预测
# -------------------------------
# class PredictRetrosyntheticPathwayInput(BaseModel):
#     product: str = Field(
#         ..., 
#         description="产物分子的 SMILES 字符串，例如 'CC(=O)O'。"
#     )

# async def predict_retrosynthetic_pathway_coroutine(product: str) -> Dict[str, Any]:
#     """
#     基于 IBM RXN 平台预测给定产物的逆合成路径，返回第一条完整路径及其反应步骤。
#     """
#     try:
#         response = rxn4chem.predict_automatic_retrosynthesis(product)
#         if "prediction_id" not in response:
#             return {"error": "无法获取 prediction_id，逆合成预测初始化失败。"}

#         prediction_id = response["prediction_id"]
#         retries = 0
#         max_retries = 10

#         while retries < max_retries:
#             results = rxn4chem.get_predict_automatic_retrosynthesis_results(prediction_id)
#             status = results.get("status", "PENDING")

#             if status == "SUCCESS":
#                 if "retrosynthetic_paths" in results and results["retrosynthetic_paths"]:
#                     path = results["retrosynthetic_paths"][0]
#                     reactions = collect_reactions(path)
#                     reaction_details = "\n".join([f"- **Reaction**: `{reaction}`" for reaction in reactions])

#                     markdown_result = f"""
# ### Retrosynthetic Pathway Prediction

# #### Product
# - **Product**: `{product}`

# #### Path
# - **Path ID**: `{path['sequenceId']}`

# #### Reactions Details
# {reaction_details}

# #### More Information
# - [IBM RXN for Chemistry](https://rxn.res.ibm.com)
# """
#                     return {"markdown": markdown_result, "path_id": path["sequenceId"], "reactions": reactions}
#                 else:
#                     return {"error": "未找到逆合成路径。"}
#             elif status in ["NEW", "PENDING", "PROCESSING"]:
#                 await asyncio.sleep(15)
#                 retries += 1
#             else:
#                 error_message = results.get("errorMessage", "未知错误。")
#                 return {"error": f"预测失败，状态: {status}, 错误信息: {error_message}"}

#         return {"error": "预测超时或超过最大重试次数。"}

#     except Exception as e:
#         return {"error": f"逆合成路径预测失败: {str(e)}"}

# predict_retrosynthetic_pathway_tool = StructuredTool.from_function(
#     coroutine=predict_retrosynthetic_pathway_coroutine,
#     name=Tools.PREDICT_RETROSYNTHETIC_PATHWAY,
#     description="""
 #   【领域：化学】
#     基于 IBM RXN 平台预测产物分子的逆合成路径。
#     输入产物 SMILES 字符串，返回第一条逆合成路径及其反应步骤（Markdown 格式）。
#     """,
#     args_schema=PredictRetrosyntheticPathwayInput,
#     metadata={"args_schema_json": PredictRetrosyntheticPathwayInput.schema()} 
# )


# -------------------------------
# Tool 3: 反应性质预测
# -------------------------------
# class PredictReactionPropertiesInput(BaseModel):
#     reactions: List[str] = Field(
#         ..., 
#         description="反应 SMILES 列表，例如 ['CCO>>CC=O', 'CN>>C=N']"
#     )

# async def predict_reaction_properties_coroutine(reactions: List[str]) -> Dict[str, Any]:
#     """
#     基于 IBM RXN 平台预测给定反应的性质（如原子映射、反应产率）。
#     """
#     try:
#         response = rxn4chem.predict_reaction_properties(
#             reactions=reactions,
#             ai_model="atom-mapping-2020"
#         )
#         properties = []
#         for item in response["response"]["payload"]["content"]:
#             properties.append(f"- **Property**: `{item['value']}`")

#         markdown_result = f"""
# ### Reaction Properties Prediction

# #### Reactions
# - **Reactions**: `{', '.join(reactions)}`

# #### Predicted Properties
# {chr(10).join(properties)}

# #### More Information
# - [IBM RXN for Chemistry](https://rxn.res.ibm.com)
# """
#         return {"markdown": markdown_result, "properties": properties}

#     except Exception as e:
#         return {"error": f"反应性质预测失败: {str(e)}"}

# predict_reaction_properties_tool = StructuredTool.from_function(
#     coroutine=predict_reaction_properties_coroutine,
#     name=Tools.PREDICT_REACTION_PROPERTIES,
#     description="""
 #   【领域：化学】
#     基于 IBM RXN 平台预测化学反应的性质（如原子-原子映射、反应产率）。
#     输入反应 SMILES 列表，返回预测性质的详细 Markdown 格式结果。
#     """,
#     args_schema=PredictReactionPropertiesInput,
#     metadata={"args_schema_json": PredictReactionPropertiesInput.schema()} 
# )
# -------------------------------




# -------------------------------
# 1. 多个SMILES生成指纹
# -------------------------------
class FingerprintsFromSmilesInput(BaseModel):
    smiles_list: List[str] = Field(
        ..., description="SMILES 字符串列表，例如 ['CCO', 'c1ccccc1', 'CC(=O)O']"
    )

async def fingerprints_from_smiles_coroutine(
    smiles_list: List[str]
) -> Dict[str, Any]:
    """
    根据输入的多个 SMILES 字符串生成分子指纹。
    返回 Markdown 格式字符串，包含分子索引、SMILES 及其对应的指纹二进制表示。
    """
    try:
        fingerprinter = Chem.RDKFingerprint
        mols = [(idx, Chem.MolFromSmiles(smi)) for idx, smi in enumerate(smiles_list)]
        res = []

        for ID, mol in mols:
            if mol:
                fp = FingerprintMols.FingerprintMol(mol, fingerprinter)
                res.append((ID, fp.ToBitString()))
            else:
                res.append((ID, f"Invalid SMILES: {smiles_list[ID]}"))

        markdown_output = "### Molecular Fingerprints\n\n"
        for idx, smi in enumerate(smiles_list):
            markdown_output += f"Index {idx}: `{smi}`\n"
        markdown_output += '\n'
        for ID, fp_str in res:
            markdown_output += f"- Molecule {ID}: `{fp_str}`\n"

        return {"fingerprints_report": markdown_output}
    except Exception as e:
        return {"error": f"生成指纹失败: {str(e)}"}

fingerprints_from_smiles_tool = StructuredTool.from_function(
    coroutine=fingerprints_from_smiles_coroutine,
    name=Tools.fingerprints_from_smiles,
    description="""
    【领域：化学】
    输入多个 SMILES 字符串，生成并返回对应的分子指纹。
    输出为 Markdown 格式，包含分子索引、SMILES 及其二进制指纹表示。
    适用于化学结构分析、相似性计算和药物筛选。
    """,
    args_schema=FingerprintsFromSmilesInput,
    metadata={"args_schema_json": FingerprintsFromSmilesInput.schema()}
)

# -------------------------------
# 2. 单个SMILES生成指纹（含二进制和十六进制）
# -------------------------------
class ProcessFingerprintMolInput(BaseModel):
    smiles: str = Field(
        ..., description="单个分子的 SMILES 字符串，例如 'CCO'"
    )

async def process_fingerprint_mol_coroutine(
    smiles: str
) -> Dict[str, Any]:
    """
    根据单个 SMILES 生成分子指纹，返回二进制和十六进制格式。
    """
    try:
        mol = Chem.MolFromSmiles(smiles)
        if mol is None:
            return {"error": "无效的 SMILES 字符串"}

        fp = FingerprintMols.FingerprintMol(mol)
        if isinstance(fp, ExplicitBitVect):
            binary_string = fp.ToBitString()
            hex_string = ''.join(
                [f'{int(binary_string[i:i+8], 2):02x}' for i in range(0, len(binary_string), 8)]
            )
            markdown_output = "### Molecular Fingerprint\n\n"
            markdown_output += f"**Binary Format:**\n`{binary_string}`\n\n"
            markdown_output += f"**Hexadecimal Format:**\n`{hex_string}`\n\n"
            return {"fingerprint_report": markdown_output}
        else:
            return {"error": "生成的指纹不是 ExplicitBitVect 类型"}
    except Exception as e:
        return {"error": f"生成指纹失败: {str(e)}"}

process_fingerprint_mol_tool = StructuredTool.from_function(
    coroutine=process_fingerprint_mol_coroutine,
    name=Tools.process_fingerprint_mol,
    description="""
    【领域：化学】
    输入一个 SMILES 字符串，生成分子指纹并返回二进制和十六进制格式。
    输出为 Markdown 格式，便于可视化和下游分析。
    适合用于单分子结构指纹分析。
    """,
    args_schema=ProcessFingerprintMolInput,
    metadata={"args_schema_json": ProcessFingerprintMolInput.schema()}
)

# -------------------------------
# 3. 折叠指纹 (Fingerprint Folding)
# -------------------------------
class FoldFingerprintFromSmilesInput(BaseModel):
    smiles: str = Field(
        ..., description="单个分子的 SMILES 字符串，例如 'c1ccccc1'"
    )
    tgtDensity: float = Field(
        0.3, description="目标稠密度 (target density)，默认 0.3"
    )
    minSize: int = Field(
        64, description="折叠后的最小指纹位数，默认 64"
    )

async def fold_fingerprint_from_smiles_coroutine(
    smiles: str,
    tgtDensity: float = 0.3,
    minSize: int = 64
) -> Dict[str, Any]:
    """
    根据 SMILES 生成分子指纹，并进行折叠处理。
    返回原始与折叠指纹的详细对比，包括比特总数和 On bits 数量。
    """
    try:
        mol = Chem.MolFromSmiles(smiles)
        if not mol:
            return {"error": "无效的 SMILES 字符串"}

        original_fp = FingerprintMols.FingerprintMol(mol)
        original_binary_fp = original_fp.ToBitString()
        original_nOn = original_fp.GetNumOnBits()
        original_nTot = original_fp.GetNumBits()

        folded_fp = FoldFingerprintToTargetDensity(
            original_fp, tgtDensity=tgtDensity, minSize=minSize
        )
        folded_binary_fp = folded_fp.ToBitString()
        folded_nOn = folded_fp.GetNumOnBits()
        folded_nTot = folded_fp.GetNumBits()

        markdown_output = "### Fingerprint Folding Details\n\n"
        markdown_output += f"**SMILES:** `{smiles}`\n\n"
        markdown_output += "**Original Fingerprint:**\n"
        markdown_output += f"`{original_binary_fp}`\n"
        markdown_output += f"Bit count: {original_nTot}, On bits: {original_nOn}\n\n"
        markdown_output += "**Folded Fingerprint:**\n"
        markdown_output += f"`{folded_binary_fp}`\n"
        markdown_output += f"Bit count: {folded_nTot}, On bits: {folded_nOn}\n\n"

        return {"folded_fingerprint_report": markdown_output}
    except Exception as e:
        return {"error": f"折叠指纹生成失败: {str(e)}"}

fold_fingerprint_from_smiles_tool = StructuredTool.from_function(
    coroutine=fold_fingerprint_from_smiles_coroutine,
    name=Tools.fold_fingerprint_from_smiles,
    description="""
    【领域：化学】
    输入一个 SMILES 字符串，生成其分子指纹并执行折叠处理。
    返回原始与折叠指纹的详细对比，包括位数和活跃位点数量。
    适用于压缩指纹表示、加速相似性计算。
    """,
    args_schema=FoldFingerprintFromSmilesInput,
    metadata={"args_schema_json": FoldFingerprintFromSmilesInput.schema()}
)


