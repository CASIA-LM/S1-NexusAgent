from typing import Any
from typing import List, Dict, Optional, Literal
import io
import aiohttp
import requests
from aiohttp import FormData
from Bio.Data.IUPACData import protein_letters_3to1  # 从Biopython获取氨基酸代码映射
from bs4 import BeautifulSoup
from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field, conint

from rdkit import Chem
from rdkit.Chem import RDConfig
import sys, os
sys.path.append(os.path.join(RDConfig.RDContribDir, 'SA_Score'))
import sascorer
 
#from admet_ai import ADMETModel
import pandas as pd
from workflow.config import EVO2, ESM3
from workflow.const import Tools
from workflow.utils.minio_utils import upload_content_to_minio



# —— . 小分子药物研发场景-根据UniProt ID 查询蛋白质信息 —— #
class ProteinIdQueryInput(BaseModel):
    """根据UniProt ID或PDB ID查询特定蛋白质详细信息的参数模型"""
    protein_id: str = Field(
        ...,
        description="**必需参数**：蛋白质的唯一标识符，通常是UniProt ID（例如 ‘P17706’, ‘Q96SW2’）或PDB ID（例如 ‘1AON’, ‘4M4K’）。",
        examples=["P17706", "Q96SW2", "1AON"] # 示例可以包含UniProt ID和PDB ID
    )
async def protein_info_info(protein_id):
    info_url = "https://gateway.taichuai.cn/protein/info"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(info_url, json={"protein_ids": [protein_id]}) as info_response:
                protein_infos = await info_response.json()
                return {
                    "data": protein_infos,
                    "columns": [
                        {
                            "title": "UniProt编号",
                            "field": "id"
                        },
                        {
                            "title": "蛋白质ID",
                            "field": "ac"
                        },
                        {
                            "title": "蛋白质描述",
                            "field": "de"
                        },
                        {
                            "title": "亚细胞定位",
                            "field": "subcellular_location"
                        },
                        {
                            "title": "序列",
                            "field": "sequence"
                        },
                        {
                            "title": "功能位点",
                            "field": "site"
                        },
                        {
                            "title": "结构域",
                            "field": "domain"
                        },
                        {
                            "title": "基因名称",
                            "field": "gen"
                        },
                    ]
                }
    except aiohttp.ClientError as e:
        return {"error": f"HTTP请求错误: {str(e)}"}
    except Exception as e:
        return {"error": f"处理错误: {str(e)}"}


protein_id_info = StructuredTool.from_function(
    coroutine=protein_info_info, # 假设这是你的原始函数
    name=Tools.PROTEIN_ID_INFO, # 更改名称以更明确其基于ID查询的特点
    description="""
    【领域：生物】
    根据提供的**蛋白质唯一标识符（UniProt ID 或 PDB ID）**，精准查找并返回该蛋白质的所有可用详细信息。
    包括其**基本属性、序列、相关结构链接**等。
    适合在用户已知具体蛋白质ID时，快速获取其所有关联数据。
    """,
    args_schema=ProteinIdQueryInput,
    metadata={"args_schema_json":ProteinIdQueryInput.schema()}
)



# —— . 小分子药物研发场景-ESM-fold 从单条氨基酸序列中预测蛋白质的三维结构 —— #

class ESMFoldInput(BaseModel):
    """ESM-fold 输入参数"""
    sequence: Optional[str] = Field(
        None,
        description="""
    【领域：生物】
        可选参数：蛋白质氨基酸序列，例如氨基酸序列为：
        MDILCEENTSLSSTTNSLMQLNDDTRLYSNDFNSGEANTSDAFNWTVDSENRTNLSCEGCLSPSCLSLLHL
        QEKNWSALLTAVVIILTIAGNILVIMAVSLEKKLQNATNYFLMSLAIADMLLGFLVMPVSMLTILYGYRWP
        LPSKLCAVWIYLDVLFSTASIMHLCAISLDRYVAIQNPIHHSRFNSRTKAFLKIIAVWTISVGISMPIPVF
        GLQDDSKVFKEGSCLLADDNFVLIGSFVSFFIPLTIMVITYFLTIKSLQKEATLCVSDLGTRAKLASFSFL
        PQSSLSSEKLFQRSIHREPGSYTGRRTMQSISNEQKACKVLGIVFFLFVVMWCPFFITNIMAVICKESCNE
        DVIGALLNVFVWIGYLSSAVNPLVYTLFNKTYRSAFSRYIQCQYKENKKPLQLILVNTIPALAYKSSQLQM
        GQKKNSKQDAKTTDNDCSMVALGKQHSEEASKDNSDGVNEKVSCV
        """
    )
    protein_id: Optional[str] = Field(
        None,
        description="可选参数，蛋白质UniProt ID，例如：P28223",
        examples=["P28223", "Q96SW2", "P0DTD1"]
    )


async def esm_fold_predict_3d(sequence: str = None, protein_id: str = None):
    if not sequence:
        if not protein_id:
            return {"error": "请提供 氨基酸序列 或者 蛋白质id"}

        # 根据蛋白质ID获取序列

        protein_url = os.environ.get("PROTEIN_URL", "")
        info_payload = {
            "protein_ids": [protein_id]
        }
        try:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=300)) as session:
                async with session.post(protein_url, json=info_payload) as response:
                    response.raise_for_status()
                    js_data = await response.json()
                    sequence = js_data[0]['sequence']

        except Exception as e:
            return {"error": f"通过蛋白质ID获取蛋白质序列错误: {str(e)}"}

    predict_3d_url = "https://gateway.taichuai.cn/esmfold/api/v1/predict"
    headers = {"Content-Type": "Application/json"}
    payload = {
        "sequence": sequence,
        "as_pdb": True
    }
    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=300)) as session:
            async with session.post(predict_3d_url, json=payload, headers=headers) as response:
                js_data = await response.json()
                return js_data
    except aiohttp.ClientError as e:
        return {"error": f"HTTP请求错误: {str(e)}"}
    except Exception as e:
        return {"error": f"处理错误: {str(e)}"}


esmfold_predict_3d_tool = StructuredTool.from_function(
    coroutine=esm_fold_predict_3d,
    name=Tools.ESM_FOLD_PREDICT_3D,
    description="""
    【领域：生物】
    根据单个蛋白质ID/氨基酸序列，预测生成对应蛋白质的三维结构文件，预测速度快，适合快速分析蛋白质。
    """,
    args_schema=ESMFoldInput,
    metadata={"args_schema_json":ESMFoldInput.schema()}
)



##################### DiffSBDD 生成与蛋白结合口袋高度匹配的小分子配体 #####################
# 测试成功

class DiffSBDDInput(BaseModel):
    """
    DiffSBDD Ligand Generation 输入参数：

    该工具基于 DiffSBDD 模型，结合蛋白质口袋结构或参考配体信息，生成
    与靶标蛋白结合的候选小分子配体。只能指定参考配体(Ref)或残基列表(Res)
    中的一个，二者必选其一。
    """
    pdb_file_url: str = Field(
        ...,
        description="必填：靶标蛋白 PDB 文件的在线 URL，确保链 ID 与残基编号一致",
        examples=["https://oss.taichuai.cn/agent/proteins/20250705/144602_clean_3RFM.pdb"]
    )
    # ref_ligand_url: Optional[str] = Field(
    #     None,
    #     description=(
    #         "可选：参考配体文件（SDF/MOL2）URL。若提供，工具将以内参配体为骨架，"
    #         "在该口袋中进行结构生成；与 `resi_list` 二选一，不能同时使用"
    #     ),
    #     examples=["https://oss.taichuai.cn/agent/ligands/example_ligand.sdf"]
    # )
    resi_list: Optional[List[str]] = Field(
        None,
        description=(
            "可选：口袋残基列表，格式为链ID:残基序号，支持插入码，如 'A:330A'。"
            "例如 ['A:331','A:332','B:101']。"
        ),
        examples=["[\"A:331\", \"A:332\"]"]
    )


async def diffsbdd_generate_ligands(
    pdb_file_url: str,
    ref_ligand_url: Optional[str] = None,
    resi_list: List[str] = None
) -> dict:
    """
    调用 DiffSBDD 接口，生成蛋白口袋高度匹配的配体分子。

    参数关系：
      - `ref_ligand_url` 与 `resi_list` 二选一，
        - 若提供 `ref_ligand_url`，则模型以内参配体引导生成；
        - 若提供 `resi_list`，则模型基于残基位置识别口袋面生成。
      - 两者不可同时为 None 或同时不为 None。

    返回：
      JSON 字典，包含生成的配体文件 URL 及相关统计信息。
    """
    # 基本请求体
    payload = {
        "pdb_file_url": pdb_file_url,
        "n_samples": 20,
        "sanitize": False,
        "relax": False,
        "is_upload": True,
        "resi_list":resi_list
    }


    url = "https://gateway.taichuai.cn/diff-sbdd/generate_ligands"
    headers = {"Content-Type": "application/json"}

    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=300)) as session:
            async with session.post(url, json=payload, headers=headers) as resp:
                resp.raise_for_status()
                return await resp.json()
    except aiohttp.ClientError as e:
        return {"error": f"HTTP 请求失败: {e}"}
    except Exception as e:
        return {"error": f"处理失败: {e}"}


diffsbdd_genrate_ligands_tool = StructuredTool.from_function(
    coroutine=diffsbdd_generate_ligands,
    name=Tools.DIFFSBDD_GENERATE_LIGANDS,
    description=(
        """
基于蛋白质结合口袋结构信息，调用 DiffSBDD 深度生成模型，设计与口袋高度匹配的小分子配体结构。

    🧠 DiffSBDD 是一种基于深度学习的结构生成方法，能够根据蛋白口袋或参考配体推断出潜在结合小分子，支持以下两种引导方式（二选一）：

    1. **参考配体引导**：
       - 参数：`ref_ligand_url`（string，必填）
       - 使用提供的参考配体文件（如 SDF/MOL2 格式）作为模型输入；
       - 适合已有候选配体的优化、衍生设计场景。

    2. **残基口袋引导**：
       - 参数：`resi_list`（List[str]，如 ["A:123", "B:45"]）
       - 根据提供的口袋残基位置（链名:残基编号）自动识别结合口袋；
       - 适合新靶点或无已知配体结构的先导设计场景。

    ⚠️ 参数规则：
    - `ref_ligand_url` 与 `resi_list` **必须二选一提供**；
    - 不可同时为空或同时同时存在，否则调用将失败。

    📦 返回内容（JSON 格式）：
    - `ligand_urls`: 生成的配体分子结构文件下载链接（如 MOL2/SDF）
    - `num_generated`: 实际生成的配体数量
    - `generation_stats`: 生成过程的统计信息（如 RMSD、对接打分等，视接口返回而定）

    ✅ 适用范围：
    - 蛋白质结构辅助的先导化合物生成
    - 基于参考配体的衍生设计
    - 无已知配体的新靶点建库起点探索

"""
    ),
    args_schema=DiffSBDDInput,
    metadata={"args_schema_json":DiffSBDDInput.schema()}
)


################# 合成可行性评估 工具（返回 JSON） ######################
# 测试成功
class SyntheticFeasibilityInput(BaseModel):
    sdf_file_url: str = Field(
        description="待评估的候选分子 SDF 文件 URL，支持 HTTP(s) 路径"
    )

async def synthetic_feasibility(sdf_file_url: str) -> Dict[str, Any]:
    """
    根据 RDKit SA_Score 方法，对 SDF 文件中每个分子计算合成可行性评分（SA Score）。
    直接返回 JSON 格式的评分列表。
    """
    # 下载 SDF 文件到内存
    async with aiohttp.ClientSession() as session:
        async with session.get(sdf_file_url) as resp:
            resp.raise_for_status()
            sdf_bytes = await resp.read()

    # 使用 BytesIO 构造 supplier 无需文件 I/O
    sdf_stream = io.BytesIO(sdf_bytes)
    suppl = Chem.ForwardSDMolSupplier(sdf_stream, removeHs=False)

    results: List[Dict[str, Any]] = []
    for idx, mol in enumerate(suppl):
        if mol is None:
            continue
        score = sascorer.calculateScore(mol)
        results.append({"mol_index": idx, "sa_score": score})

    return {"sa_scores": results}

synthetic_feasibility_tool = StructuredTool.from_function(
    coroutine=synthetic_feasibility,
    name=Tools.SYNTHETIC_FEASIBILITY,
    description="""
    [领域：生物]
    对输入的候选分子 SDF 文件（URL）逐一分子计算合成可行性分数（SA Score），
    基于 RDKit SA_Score 算法，直接以 JSON 列表形式返回每个分子的评分，
    适用于小分子库快速筛选与可合成性评估。
    """,
    args_schema=SyntheticFeasibilityInput,
    metadata={"args_schema_json":SyntheticFeasibilityInput.schema()}

)


#   获取蛋白质信息，输出pdb、
# 测试成功
class ProteinGeneralQueryInput(BaseModel):
    """用于根据多种条件查询蛋白质基本信息的参数模型"""
    protein_name: Optional[str] = Field(
        None,
        description="可选参数：目标蛋白的通用名称或常用缩写，例如 ‘ADORA2A’, ‘EGFR’。与 organism 或 pdb_id 结合使用以精确查询。请注意：若用户未提供该参数默认为‘None’，必须传入！"
    )
    organism: Optional[str] = Field(
        None,
        description="可选参数：目标蛋白所属的物种名称，例如 ‘Homo sapiens’, ‘Mus musculus’。用于缩小搜索范围。请注意：若用户未提供该参数默认为‘None’，必须传入！"
    )
    pdb_id: Optional[str] = Field(
        None,
        description="可选参数：蛋白质在PDB数据库中的结构ID，例如 ‘3RFM’, ‘7K43’。如果已知PDB ID，可以直接获取相关结构信息。请注意：若用户未提供该参数默认为‘None’，必须传入！"
    )

async def get_protein_info(
    protein_name: Optional[str] = None,
    organism: Optional[str] = None,
    pdb_id: Optional[str] = None
) -> Dict[str, Any]:
    """
    调用后端微服务获取指定蛋白的 UniProt ID、基因名、物种、氨基酸序列（FASTA）及 PDB 结构文件 URL。
    返回结构化的 JSON，包括：
      - uniprot_id
      - gene_name
      - organism
      - sequence (FASTA 格式文本)
      - sequence_url (FASTA 文件下载链接)
      - pdb_id
      - pdb_url (原始 PDB 文件链接)
      - cleaned_pdb_url (去除溶剂和配体的清洁 PDB 文件链接)
    """
    url = "https://gateway.taichuai.cn/mini-tool/get_protein_info"
    payload = {
        "protein_name": protein_name,
        "organism": organism,
        "pdb_id": pdb_id
    }
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload) as resp:
                resp.raise_for_status()
                return await resp.json()
    except aiohttp.ClientError as e:
        return {"error": f"HTTP 请求错误: {str(e)}"}
    except Exception as e:
        return {"error": f"处理错误: {str(e)}"}

get_protein_detailed_info_tool = StructuredTool.from_function(
    coroutine=get_protein_info, # 假设这是你的原始函数
    name=Tools.GET_PROTEIN_DETAILED_INFO, # 更改名称以更明确其通用性
    description="""
    【领域：生物】
    根据提供的**蛋白质名称、所属物种或 PDB ID** 查询蛋白质的详细资料。

    返回结构化的 JSON，包括：
      - uniprot_id
      - gene_name
      - organism
      - sequence (FASTA 格式文本)
      - sequence_url (FASTA 文件下载链接)
      - pdb_id
      - pdb_url (原始 PDB 文件链接)
      - cleaned_pdb_url (去除溶剂和配体的清洁 PDB 文件链接)
    """,
    args_schema=ProteinGeneralQueryInput,
    metadata={"args_schema_json":ProteinGeneralQueryInput.schema()}
)