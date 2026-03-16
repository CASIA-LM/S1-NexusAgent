import uuid

import json
import logging
import random
from typing import Any
from typing import List, Dict, Optional, Literal

import aiohttp
import requests
from aiohttp import FormData
from Bio.Data.IUPACData import protein_letters_3to1  # 从Biopython获取氨基酸代码映射
from bs4 import BeautifulSoup
from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field, conint
from pydantic import validator

from workflow.config import EVO2, ESM3
from workflow.const import Tools
from workflow.utils.minio_utils import upload_content_to_minio
from datetime import datetime, timedelta
from Bio import Entrez, SeqIO
from io import BytesIO, StringIO

# —— . 小核酸药物研发场景-mRNA设计siRNA 和脱靶效应、毒性 —— #
class OligoformerInput(BaseModel):
    """Oligoformer 工具的输入参数模型"""
    mRNA: str = Field(...,
                      description="需要提供的mRNA, 用来生成siRNA, 例如: AUGCCGUAUACGGUACGUAAUGGCCGUGACUUUAAACGGGUUCCUUGGAAAUAACCCGGGGAAUGACGUACGUAAUGGGCCGUGACUUUAAACGGGUUCCUUGGAAAUAACCCGGGGAUUCUAG")
    top_n: Optional[int] = Field(
        10,
        description="只计算前n个siRNA(-1表示全部)"
    )
    no_func: Optional[bool] = Field(True, description="是否禁用功能性过滤")
    off_target: Optional[bool] = Field(False, description="是否检查脱靶效应")
    toxicity: Optional[bool] = Field(False, description="是否检查毒性")


async def oligoformer_infer(
        mRNA: str,
        no_func: bool = True,
        off_target: bool = False,
        toxicity: bool = False,
        top_n: int = 10
) -> dict:
    url = "https://gateway.taichuai.cn/oligo-former/infer"
    print("\n")
    print("######test_oligo#######")
    print("\n")
    # 构造请求负载
    payload = {
        "mRNA": [mRNA],
        "config": {
            "no_func": no_func,
            "off_target": off_target,
            "toxicity": toxicity,
            "top_n": top_n
        },

    }

    # 使用aiohttp发起异步请求
    async with aiohttp.ClientSession() as session:
        try:
            async with session.post(url, json=payload) as response:
                response.raise_for_status()  # 检查HTTP状态码
                return await response.json()  # 返回JSON结果

        except aiohttp.ClientError as e:
            return {"error": f"API请求失败: {str(e)}"}
        except json.JSONDecodeError as e:
            return {"error": "响应解析失败"}


# 创建结构化工具
oligoformer_tool = StructuredTool.from_function(
    coroutine=oligoformer_infer,
    name=Tools.OLIGO_FORMER,
    description="""
    【领域：生物】用于小核酸预测siRNA对给定mRNA序列的抑制效果的工具，可以自动设计并推荐高效靶向特定 mRNA 的 siRNA 分子""",
    args_schema=OligoformerInput,
    metadata={"args_schema_json": OligoformerInput.schema()}
)


# 小核酸

# 预测单链 RNA 自折叠二级结构的工具输入参数模型

class SecondaryStructureInput(BaseModel):
    """预测单链 RNA 自折叠二级结构的工具输入参数模型"""
    sequence: str = Field(
        ...,
        description="RNA 序列，例如: UACUCCACACGCAAAUUUC"
    )

async def predict_rna_secondary_structure_infer(sequence: str) -> dict:
    """
    使用 RNAfold 本地工具预测 RNA 自折叠二级结构（dot-bracket 格式）和自由能。
    """

    import subprocess

    try:
        # RNAfold 接收标准输入中的序列，格式要求每行为一个序列（无标题）
        process = subprocess.run(
            ["RNAfold", "--noPS"],
            input=sequence.encode(),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )

        if process.returncode != 0:
            return {"error": f"RNAfold 执行失败: {process.stderr.decode()}"}

        output_lines = process.stdout.decode().strip().splitlines()

        if len(output_lines) < 2:
            return {"error": f"RNAfold 输出格式异常: {output_lines}"}

        # 输出形式为：
        # sequence
        # structure (free_energy)
        # 例如：
        # UACUCCACACGCAAAUUUC
        # ..(((...)))....... (-3.20)

        structure_line = output_lines[1]
        parts = structure_line.strip().rsplit(" ", 1)  # 从右边分割最后一个字段（能量）
        if len(parts) != 2:
            return {"error": f"RNAfold 结构行格式错误: {structure_line}"}

        dot_bracket = parts[0].strip()
        try:
            free_energy = float(parts[1].strip("()"))
        except ValueError:
            return {"error": f"RNAfold 自由能解析失败: {parts[1]}"}

        return {
            "structure": dot_bracket,
            "free_energy_kcal_per_mol": free_energy,
            "message": "成功预测 RNA 自折叠二级结构"
        }

    except FileNotFoundError:
        return {"error": "RNAfold 未安装或未在 PATH 中"}
    except Exception as e:
        return {"error": f"内部错误: {str(e)}"}


# 创建结构化工具
predict_rna_secondary_structure_tool = StructuredTool.from_function(
    coroutine=predict_rna_secondary_structure_infer,
    name=Tools.PREDICT_RNA_SECONDARY_STRUCTURE,
    description="""
    【领域：生物】
    预测单链 RNA 序列的自折叠二级结构及自由能的工具。
    返回字段：
    - structure: 二级结构的 dot-bracket 表示法
    - free_energy_kcal_per_mol: 预测的自由能 (ΔG)，单位 kcal/mol
    - message: 预测状态提示，如“成功预测 RNA 自折叠二级结构”或错误信息
    """,
    args_schema=SecondaryStructureInput,
    metadata={"args_schema_json": SecondaryStructureInput.schema()}
)


#计算单个 siRNA 与目标 mRNA 结合自由能
class BindingEnergyInput(BaseModel):
    """计算单个 siRNA 与目标 mRNA 结合自由能的工具输入参数模型"""
    sirna_seq: str = Field(...,
                          description="siRNA 序列，例如: UCGCAAAUUAAAUUGAACC")
    target_mrna_seq: str = Field(...,
                                 description="目标 mRNA 序列，例如: GGUUCAAUUUAAUUUGCGAAAGAGACCUUACGGACGUGGGCGCCAGUGGACCUCCUC")


async def calculate_binding_energy_infer(

        sirna_seq: str,
        target_mrna_seq: str
) -> dict:
    """
    计算 siRNA 与目标 mRNA 的结合自由能及杂交结构。

    返回示例:
    {
      "hybrid_seq": "UCGCAAAUUAAAUUGAACC&GGUUCAAUUUAAUUUGCGAAAGAGACCUUACGGACGUGGGCGCCAGUGGACCUCCUC",
      "structure": "((((((((((((((((((()))))))))))))))))))..(((..((.((((.((....)))).))))..)))...",
      "binding_energy_kcal_per_mol": -31.799999237060547,
      "message": "成功计算siRNA与mRNA的结合能"
    }
    """
    url = "https://gateway.taichuai.cn/mini-tool/calculate_binding_energy"
    print("\n")
    print("######BindingEnergy#######")
    print("\n")

    payload = {
        "sirna_seq": sirna_seq,
        "target_mrna_seq": target_mrna_seq
    }

    async with aiohttp.ClientSession() as session:
        try:
            async with session.post(url, json=payload) as response:
                response.raise_for_status()
                return await response.json()

        except aiohttp.ClientError as e:
            return {"error": f"API 请求失败: {str(e)}"}
        except json.JSONDecodeError:
            return {"error": "响应解析失败"}

binding_energy_tool = StructuredTool.from_function(
    coroutine=calculate_binding_energy_infer,
    name=Tools.CALCULATE_BINDING_ENERGY,
    description="""
    【领域：生物】【siRNA–mRNA 杂交预测工具】
    本工具专门用于计算单条 siRNA 分子与其靶标 mRNA 之间的双链杂交二级结构和结合自由能。
    返回字段：
    - hybrid_seq: 杂交后的双链序列，用 “&” 分隔（siRNA&mRNA）
    - structure: 杂交二级结构的 dot‑bracket 表示法，反映两条链之间的碱基配对
    - binding_energy_kcal_per_mol: Gibbs 自由能 (ΔG)，单位 kcal/mol；数值越负表示结合越稳定
    - message: 运行状态或出错提示，如“成功计算 siRNA–mRNA 杂交自由能”或详细的错误信息
    """,
    args_schema=BindingEnergyInput,
    metadata={"args_schema_json": BindingEnergyInput.schema()}
)


# 设置邮箱
#Entrez.email = "your_email@example.com"
class FetchMrnaSequenceInput(BaseModel):
    gene_name: str = Field(
        ..., description="目标疾病靶点基因的名称，如 TP53"
    )

async def fetch_mrna_sequence_coroutine(
    gene_name: str
) -> Dict[str, Any]:
    """
    根据用户输入的基因名称，在 NCBI 中检索 Homo sapiens mRNA 序列，
    将其保存为 FASTA 格式，上传到 MinIO，并返回可下载的预签名 URL 及序列文本。
    """
    try:

        # 1. 使用 Entrez 搜索 mRNA
        handle = Entrez.esearch(
            db="nucleotide",
            term=f"{gene_name}[Gene] AND Homo sapiens[Organism] AND mRNA",
            retmax=1
        )
        record = Entrez.read(handle)
        handle.close()

        if not record.get("IdList"):
            return {"error": f"未找到基因 {gene_name} 的 mRNA 序列。"}

        seq_id = record["IdList"][0]
        handle = Entrez.efetch(
            db="nucleotide",
            id=seq_id,
            rettype="fasta",
            retmode="text"
        )
        seq_record = SeqIO.read(handle, "fasta")
        handle.close()
        
        # 3. 对序列部分截断
        full_seq = str(seq_record.seq)
        truncated_seq = full_seq[:500]

        # 2. 将序列写入内存字符串缓冲区
        txt_buffer = StringIO()
        SeqIO.write(seq_record, txt_buffer, "fasta")
        fasta_str = txt_buffer.getvalue()
        fasta_data = fasta_str.encode('utf-8')  # 转为字节流


        # 3. 生成文件名：带时间前缀 + 基因名
        now = datetime.now().strftime("%Y%m%d/%H%M%S")
        filename_base = f"{gene_name}_mRNA"
        file_name = f"{now}_{filename_base}.fasta"

        # 4. 上传到 MinIO
        file_url = await upload_content_to_minio(
            content=fasta_data,
            file_name=file_name,
            file_extension=".fasta",
            content_type="text/plain",
            no_expired=True,
        )

        # 返回文件 URL 及序列文本
        return {
            "mRNA_fasta_file_url": file_url,
            "sequence": truncated_seq
        }

    except Exception as e:
        return {"error": f"检索或上传过程出错: {str(e)}"}

# 工具实例化
fetch_mrna_sequence_tool2 = StructuredTool.from_function(
    coroutine=fetch_mrna_sequence_coroutine,
    name=Tools.FETCH_MRNA_SEQUENCE2,
    description="""
    【领域：生物】
    根据目标疾病靶点基因名称如TP53，检索 Homo sapiens 的 mRNA 序列，
    并返回对应的 FASTA 文件 URL 及序列文本。
    """,
    args_schema=FetchMrnaSequenceInput,
    metadata={"args_schema_json": FetchMrnaSequenceInput.schema()}
)
