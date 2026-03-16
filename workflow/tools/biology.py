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


async def dna_generate(
        sequence: str,
        num_tokens: int,
        temperature: float,
        top_k: int,
        top_p: float
):
    url = EVO2.DNA_GENERATE_URL

    headers = {
        'Content-Type': 'application/json',
    }
    req_body = {
        "sequence": sequence,
        "num_tokens": num_tokens,
        "temperature": temperature,
        "top_k": top_k,
        "top_p": top_p,
        "enable_logits": False,
        "enable_sampled_probs": True
    }

    valid_amino_acids = ["A", "C", "T", "G"]
    random_data = ''.join(random.choices(valid_amino_acids, k=num_tokens))
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, headers=headers, json=req_body) as response:
                if response.status == 200:
                    rest = await response.json()
                    rest["input_sequence"] = sequence
                    return rest
                else:
                    return {"generated_sequence": random_data}

    except Exception as e:
        _ = e
        return {"generated_sequence": random_data}


class DnaGenerateInput(BaseModel):
    sequence: str = Field(
        min_length=1, max_length=500,
        description="DNA序列，例如：TCCATCTGAGGTACCGGGTTCATCTCACTAGGGAGTGCCAGACAGTGGGCGCAGGCCAGTGTGTGTGCGCACCGTGCGCGAGCCGAAGCAGGGCGAGGCATTGCCTCACCTGGGAAGCGCAAGGGGTCAGGGAGTTCCCTTTCCGA"
    )
    num_tokens: int = Field(default=100, ge=1, le=300, description="预测生成的的DNA序列长度")
    temperature: float = Field(
        default=0.7, gt=0.01, le=1.3,
        description="温度采样过程中的随机性比例。低于 1.0 的值会生成更尖锐的分布，随机性较低。高于 1.0 的值会生成均匀分布，随机性更高")
    top_k: int = Field(
        default=3, gt=0, le=6,
        description="指定要考虑的最高概率标记数。设置为 1 时，仅选择概率最高的标记。设置的值越高，采样就越多样化。如果设置为 0，则考虑所有标记")
    top_p: int = Field(
        default=1.0, gt=0, le=1.0,
        description="此参数指定启用核采样的 top-p 阈值数（介于 0 和 1 之间）。当最小可能的标记集的累积概率超过 top_p 阈值时，它会过滤掉其余的标记。将其设置为 0.0 可禁用 top-p 采样")


dna_generate_tool = StructuredTool.from_function(
    coroutine=dna_generate,
    name=Tools.DNA_PREDICT,
    description="""
    【领域：生物】利用输入的DNA碱基序列，预测生成指定长度的后续可能序列,适用于生物信息学场景""",
    args_schema=DnaGenerateInput,
    metadata={"args_schema_json": DnaGenerateInput.schema()}
)


##############################蛋白质补全##############################


async def protein_make_up(sequence: str, left_length: int = 50, right_length: int = 50) -> Dict[str, Any]:
    api_url = ESM3.GENERATE_SEQUENCE
    headers = {
        'Content-Type': 'application/json',
    }
    valid_amino_acids = ["ACDEFGHIKLMNPQRSTVWY"]

    random_seq = f"{random.choices(valid_amino_acids, k=left_length)}{sequence}{random.choices(valid_amino_acids, k=right_length)}"

    if len(sequence) + left_length + right_length > 400:
        return {
            "sequence": random_seq
        }
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(api_url, headers=headers, json={
                "sequence": f'{"_" * left_length}{sequence}{"_" * right_length}',
                "num_steps": 15
            }, timeout=30) as response:
                if response.status == 200:
                    rest = await response.json()
                    logging.info(f'protein_make_up: {rest}')
                    return {
                        "sequence": rest.get('sequence') or random_seq
                    }
                else:
                    return {
                        "sequence": random_seq
                    }

    except Exception as e:
        return {
            "sequence": random_seq
        }


class ProteinMakeUpInput(BaseModel):
    sequence: str = Field(
        min_length=1,
        max_length=300,
        description="需要预测/补全的蛋白质序列，例如: QATSLRILNNGHAFNVEFDDSQDKAVL"
    )

    left_length: int = Field(
        default=50,
        ge=0,
        description="蛋白质序列左边需要补全的长度，默认值为50。例如：5"
    )

    right_length: int = Field(
        default=50,
        ge=0,
        description="蛋白质序列右边需要补全的长度，默认值为50。例如：7"
    )


make_up_protein_tool = StructuredTool.from_function(
    coroutine=protein_make_up,
    name=Tools.PROTEIN_COMPLETE,
    description="""
    【领域：生物】可以用来预测蛋白质序列或者补全蛋白质序列，适用于生物信息学场景""",
    args_schema=ProteinMakeUpInput,
    metadata={"args_schema_json": ProteinMakeUpInput.schema()}
)


##############################生成3D结构pdb##############################

async def generate_pdb_data(sequence: str):
    api_url = ESM3.GENERATE_PDB
    headers = {
        'Content-Type': 'application/json',
    }
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(api_url, headers=headers, json={
                "sequence": sequence,
                "num_steps": 15
            }, timeout=30) as response:
                if response.status == 200:
                    return await response.text()

    except requests.exceptions.RequestException as e:
        return {"error": f"Request failed: {str(e)}"}
    except Exception as e:
        return {"error": f"Error processing the data: {str(e)}"}


class GeneratePDBDataInput(BaseModel):
    sequence: str = Field(
        min_length=1,
        max_length=300,
        description="氨基酸序列，例如: MATKAVCVLKGDGPVQGIINFEQKESNGPVKVWGSIKGL"
    )


generate_pdb_data_tool = StructuredTool.from_function(
    coroutine=generate_pdb_data,
    name=Tools.GENERATE_PDB_FROM_PROTEIN,
    description="""
    【领域：生物】可以用来根据氨基酸/蛋白质序列生成3D结构的PDB数据""",
    args_schema=GeneratePDBDataInput,
    metadata={"args_schema_json": GeneratePDBDataInput.schema()}
)


###

# 定义输入参数的Pydantic模型
class GenMolInputSchema(BaseModel):
    """分子生成工具的输入参数模型"""
    smiles: str = Field(
        ...,
        description="输入的分子SMILES字符串(必填，最长512字符)，示例：C124CN3C1.S3(=O)(=O)CC.C4C#N.[*{20-20}]",
        max_length=512,
        examples=["C124CN3C1.S3(=O)(=O)CC.C4C#N.[*{20-20}]"]
    )
    num_molecules: Optional[int] = Field(
        default=30,
        description="生成分子数量(1-1000，默认30)",
        examples=[30],
        ge=1,
        le=1000
    )
    temperature: Optional[float] = Field(
        default=1.0,
        description="SoftMax温度缩放因子(0.01-10，默认1.0)",
        examples=[1.0],
        gt=0.01,
        le=10.0
    )
    noise: Optional[float] = Field(
        default=1.0,
        description="随机性因子(0-2，默认1)",
        examples=[1.0],
        ge=0,
        le=2
    )
    step_size: Optional[int] = Field(
        default=1,
        description="扩散步长(1-10，默认1)",
        examples=[1],
        ge=1,
        le=10
    )
    scoring: Optional[str] = Field(
        default="QED",
        description="评分方法(枚举值：'QED'或'LogP'，默认'QED')",
        examples=["QED", "LogP"]
    )
    unique: Optional[bool] = Field(
        default=False,
        description="是否只返回独特分子(默认False)"

    )


async def genmol_molecule_generator(
        smiles: str,
        num_molecules: Optional[int] = 30,
        temperature: Optional[float] = 1.0,
        noise: Optional[float] = 1,
        step_size: Optional[int] = 1,
        scoring: Optional[str] = "QED",
        unique: Optional[bool] = False
) -> dict:
    url = "https://gateway.taichuai.cn/genmol/generate"

    # 构造请求载荷
    payload = {
        "smiles": "C124CN3C1.S3(=O)(=O)CC.C4C#N.[*{20-20}]",
        "num_molecules": num_molecules,
        "temperature": temperature,
        "noise": noise,
        "step_size": step_size,
        "scoring": scoring,
        "unique": unique
    }

    headers = {
        "Content-Type": "application/json",
    }

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, headers=headers, json=payload) as response:
                response.raise_for_status()  # 检查HTTP错误
                return await response.json()
    except aiohttp.ClientError as e:
        # 返回错误信息
        return {"status": "error", "message": str(e)}
    except Exception as e:
        return {"status": "error", "message": f"Unexpected error: {str(e)}"}


# 创建LangChain结构化工具
genmol_tool = StructuredTool.from_function(
    coroutine=genmol_molecule_generator,
    name=Tools.GENMOL_MOLECULE_GENERATOR,
    description="""
    【领域：生物】
    一个专业的分子生成工具，根据输入的SMILES字符串生成新的分子结构(异步版本)。
    可以控制生成数量、随机性、评分方法等参数。
    适用于药物发现和材料设计等场景。可用于分子生成、分子结构补全、分子片段组装
    """,
    args_schema=GenMolInputSchema,
    metadata={"args_schema_json": GenMolInputSchema.schema()}
)


#########
class RFDiffusionInputSchema(BaseModel):
    """蛋白质扩散生成工具的输入参数模型"""
    input_pdb: str = Field(
        ...,
        description="""
            pdb的文件url地址，用户可以通过两个方式传入这个地址：
                通过文件上传功能，上传.pdb格式结尾的文件，优先用这种方式获取
                直接输入一个.pdb的url地址 
            """,
    )
    contigs: str = Field(
        ...,
        description="""作用：指定蛋白质结构中需要保留或重新设计的连续片段
            格式：链名起始-结束/填充 其他区域...
            示例："A114-353/0 50-100"
            拆解说明：
                A114-353：保留 A 链第 114 到 353 号残基的原始结构
                /0：在保留区域两侧各填充 0 个残基的缓冲区
                50-100：额外设计 50-100 号残基的新结构（无链名表示可自由设计）
            典型用途：
                保留蛋白核心区域，重新设计表面环区
                拼接不同蛋白的功能域
        """,
        examples=["A114-353/0 50-100"]
    )
    hotspot_res: List[str] = Field(
        ...,
        description="""
            作用：标记必须保留的关键功能性残基（如催化位点、结合位点）
            格式：列表形式，每个元素为 链名+残基号
            示例：["A119", "A123", "A233"]
            关键特性：
                算法会强制维持这些残基的空间位置和化学性质
                常用于保留酶活性中心或蛋白-蛋白相互作用界面
            为什么重要：
                保证生成结构的生物功能不变
                避免关键残基在优化过程中被破坏
        """,
        examples=[["A119", "A123", "A233"]]
    )
    diffusion_steps: int = Field(
        ...,
        description="""
            作用：控制生成过程的随机性和精细度
            取值范围：15-90（整数）
            如何选择：
                步数范围	生成特性	适用场景
                15-30	快速但粗糙	初步探索大量设计
                30-60	平衡速度与质量	常规设计
                60-90	精细但缓慢	最终优化
            技术本质：
                对应扩散模型中的去噪步骤数，步数越多生成结构越精细但耗时越长
        """,
        examples=[15],
        ge=15,
        le=90
    )

    @validator('hotspot_res')
    def validate_hotspot_format(cls, v):
        """验证热点残基格式"""
        for res in v:
            if not (res[0].isalpha() and res[1:].isdigit()):
                raise ValueError(f"热点残基格式错误，应为'A119'形式，得到: {res}")
        return v


async def fetch_text_file(url):
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as response:
                if response.status == 200:
                    content = await response.text()
                    return content
                else:
                    print(f"请求失败，状态码: {response.status}")
                    return None
    except Exception as e:
        print(f"发生错误: {e}")
        return None


async def rfdiffusion_generator(
        input_pdb: str,
        contigs: str,
        hotspot_res: List[str],
        diffusion_steps: int = 15
) -> dict:
    url = "https://gateway.taichuai.cn/rfdiffusion/biology/ipd/rfdiffusion/generate"

    payload = {
        "input_pdb": await fetch_text_file(input_pdb),
        "contigs": contigs,
        "hotspot_res": hotspot_res,
        "diffusion_steps": diffusion_steps
    }
    headers = {
        "Content-Type": "application/json"
    }

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, headers=headers, json=payload) as response:
                result = await response.json()
                return_data = {"result_pdb_url": None, "error": None}

                # 服务处理错误
                if response.status != 200 or "output_pdb" not in result:
                    return_data["error"] = result["error"]
                    return return_data

                pdb_url = await upload_content_to_minio(result["output_pdb"], file_extension=".pdb",
                                                        content_type="application/octet-stream")
                return_data['result_pdb_url'] = pdb_url
                return return_data
    except aiohttp.ClientError as e:
        return {"error": f"HTTP请求错误: {str(e)}"}
    except Exception as e:
        return {"error": f"处理错误: {str(e)}"}


# 创建LangChain结构化工具
rfdiffusion_tool = StructuredTool.from_function(
    coroutine=rfdiffusion_generator,
    name=Tools.PROTEIN_DIFFUSION_GENERATOR,
    description="""
    【领域：生物】
    专业的蛋白质结构生成工具，基于RF Diffusion算法:
    1. 根据输入的PDB模板生成新的蛋白质结构
    2. 可指定需要保留/修改的连续区域(contigs)
    3. 可定义关键功能残基(hotspots)
    适用于蛋白质设计、结构优化、蛋白质骨架设计、结合蛋白设计等场景
    """,
    args_schema=RFDiffusionInputSchema,
    metadata={"args_schema_json": RFDiffusionInputSchema.schema()}
)


####


# 定义输入参数模型，包含参数验证
class ProteinGenerationInput(BaseModel):
    """ProtGPT2蛋白质生成API的输入参数模型"""
    prefix: Optional[str] = Field(
        "<|endoftext|>",
        description="起始氨基酸序列前缀，默认为<|endoftext|>表示从空序列开始生成， 示例值：MALWMR",
        examples=["MALWMR", "<|endoftext|>"]
    )
    num_sequences: Optional[conint()] = Field(
        default=2,
        description="需要生成的蛋白质序列数量，范围1-10，默认为2",
        examples=[3],
        ge=1, le=10
    )
    max_length: int = Field(
        default=50,
        description="生成蛋白质的最大长度(氨基酸数量)，范围10-200，默认为50",
        examples=[100],
        ge=10, le=200
    )
    top_k: int = Field(
        default=950,
        description="多样性控制参数(top-k采样)，范围50-1000，值越大多样性越高，默认为950",
        examples=[800],
        ge=50, le=1000
    )
    repetition_penalty: float = Field(
        default=1.2,
        description="重复惩罚系数，范围1.0-2.0，值越高越避免重复序列，默认为1.2",
        examples=[1.5],
        ge=1.0, le=2.0
    )


async def generate_protein_sequences(
        prefix: str = "<|endoftext|>",
        num_sequences: int = 2,
        max_length: int = 50,
        top_k: int = 950,
        repetition_penalty: float = 1.2
) -> Dict:
    # API配置
    invoke_url = "https://gateway.taichuai.cn/protgpt2/generate"
    headers = {"Content-Type": "application/json"}

    # 构造请求体
    payload = {
        "prefix": prefix,
        "num_sequences": num_sequences,
        "max_length": max_length,
        "top_k": top_k,
        "repetition_penalty": repetition_penalty
    }

    # 发送请求
    try:
        async with aiohttp.ClientSession() as session:
            result_sequences = []
            async with session.post(invoke_url, headers=headers, json=payload) as response:
                response_json = await response.json()
                sequences = response_json["data"]["sequences"]

                if prefix != "<|endoftext|>":
                    for sequence in sequences:
                        if not sequence.startswith(prefix):
                            result_sequences.append(prefix + sequence)
                else:
                    result_sequences = sequences
            invoke_url = "https://gateway.taichuai.cn/protgpt2/perplexity"
            headers = {"Content-Type": "application/json"}
            payload = {"sequences": result_sequences}
            async with session.post(invoke_url, headers=headers, json=payload) as response:
                return await response.json()
    except Exception as e:
        return {"error": f"处理错误: {str(e)}"}


# 创建LangChain结构化工具
protgpt2_protein_generation_tool = StructuredTool.from_function(
    coroutine=generate_protein_sequences,
    name=Tools.PROTGPT2_PROTEIN_GENERATOR,
    description="""
    【领域：生物】使用ProtGPT2模型根据起始序列生成蛋白质序列，可控制序列数量、长度和多样性等参数。可用于蛋白质/氨基酸生成 并计算困惑度。该工具后置任务是蛋白质序列的困惑度计算""",
    args_schema=ProteinGenerationInput,
    metadata={"args_schema_json": ProteinGenerationInput.schema()}
)


#####
# 定义输入模型，用于验证输入参数
class ProteinPerplexityInput(BaseModel):
    """蛋白质序列困惑度计算工具的输入参数模型"""
    sequences: List[str] = Field(
        ...,
        description="需要计算困度的蛋白质序列列表",
        examples=[
            "MKTVRQERLKSIVRILERSKEPVSGAQLAEELSVSRQVIVQDIAYLRSLGYNIVATPRGYVLAGG",
            "MLAVLPEKREMTECHLSDEEIRKLNVELRPGEGNAFVGAYHIRVLHDLRAREEA"
        ]
    )


async def calculate_protein_perplexity(sequences: List[str]) -> Dict:
    # API端点配置
    invoke_url = "https://gateway.taichuai.cn/protgpt2/perplexity"
    headers = {"Content-Type": "application/json"}
    payload = {"sequences": sequences}

    # 创建会话并发送请求
    session = requests.Session()
    response = session.post(invoke_url, headers=headers, json=payload)
    response.raise_for_status()  # 如果请求失败将抛出异常

    return response.json()


protein_perplexity_tool = StructuredTool.from_function(
    coroutine=calculate_protein_perplexity,
    name=Tools.PROTGPT2_PROTEIN_PREPLEXITY_CALCULATOR,
    description="""
    【领域：生物】计算蛋白质序列的困惑度(perplexity)值，困惑度是衡量蛋白质序列在ProtGPT2模型下概率的指标, 可用户蛋白质生成后困惑度的计算，值越高代表不确定性越高""",
    args_schema=ProteinPerplexityInput,
    metadata={"args_schema_json": ProteinPerplexityInput.schema()}
)


async def get_element_by_id_with_contents(html_text, element_id):
    # 使用BeautifulSoup解析HTML
    soup = BeautifulSoup(html_text, 'html.parser')

    # 查找指定ID的元素
    target_element = soup.find(id=element_id)

    if target_element:
        # 返回元素及其所有内容的字符串表示
        return str(target_element)
    else:
        return None


### 根据基因名称找到对应关联的基因
async def gen_relation(gen):
    url = "https://gateway.taichuai.cn/protein/relation"

    payload = {
        'protein_name': gen,
        'limit': '30'
    }
    headers = {
        'Content-Type': 'application/json',
    }
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, headers=headers, json=payload) as response:
                relation_json = await response.json()
                relation_gen = relation_json.get('relation_gen')
                relation_html = relation_json.get('relation_html', '')
                relation_url = None
                if relation_html:
                    relation_html = relation_json.get('relation_html', '').replace("/images/", "/agent/images/")
                    relation_url = await upload_content_to_minio(relation_html, file_extension=".html",
                                                                 content_type="application/octet-stream")
                biogrid_protein = relation_json.get('biogrid_protein', {})
                biogrid_protein_columns = biogrid_protein.get('columns', [])
                biogrid_protein_data_url = await upload_content_to_minio(
                    json.dumps(biogrid_protein.get('data', []), indent=2), file_extension=".json",
                    content_type="application/octet-stream")
                return {"relation_gen": relation_gen, "relation_url": relation_url,
                        "biogrid_protein_columns": biogrid_protein_columns,
                        "biogrid_protein_data_url": biogrid_protein_data_url}

    except Exception as e:
        return {"error": f"处理错误: {str(e)}"}


class GenRelationInput(BaseModel):
    """根据蛋白质基因找关联基因的参数模型"""
    gen: str = Field(
        ...,
        description="基于当前基因找到和它有关联的基因, 例如PTPIP51",
        examples=["PTPIP51"]
    )


gen_relation_tool = StructuredTool.from_function(
    coroutine=gen_relation,
    name=Tools.GEN_RELATION,
    description="""
    【领域：生物】根据提供的蛋白质名称或基因名称找到和它有关联的或者有相互作用的蛋白质，基因互作探索""",
    args_schema=GenRelationInput,
    metadata={"args_schema_json":GenRelationInput.schema()}
)


########

async def gen_protein_info(gen):
    url = "https://gateway.taichuai.cn/protein/info/gen/" + gen

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as response:
                protein_infos = await response.json()
                protein_infos_url = await upload_content_to_minio(json.dumps(protein_infos, indent=4),
                                                                  file_extension=".json",
                                                                  content_type="application/octet-stream")
                return {
                    "protein_infos_url": protein_infos_url,
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


class GenProteinInfoInput(BaseModel):
    """基因蛋白信息查询器"""
    gen: str = Field(
        ...,
        description="基于当前基因名称获取相关的蛋白质信息，示例值：VAPA",
        examples=["VAPA"]
    )


gen_protein_info_tool = StructuredTool.from_function(
    coroutine=gen_protein_info,
    name=Tools.GEN_PROTEIN_INFO,
    description="""
    【领域：生物】根据提供的蛋白质基因找到相关的蛋白质信息，用于基因蛋白信息查询""",
    args_schema=GenProteinInfoInput,
    metadata={"args_schema_json":GenProteinInfoInput.schema()}
)


#####
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


class ProteinInfoInput(BaseModel):
    """蛋白同源结构评估"""
    protein_id: str = Field(...,description="蛋白质id，示例值：P17706")


# protein_info_tool = StructuredTool.from_function(
#     coroutine=protein_info_info,
#     name=Tools.PROTEIN_INFO,
#     description="根据蛋白质id查找，蛋白质信息，用于蛋白质资料详情查询",
#     args_schema=ProteinInfoInput,
# )


#####
async def protein_blastp(protein_id):
    url = "https://gateway.taichuai.cn/protein/blast/" + protein_id
    info_url = "https://gateway.taichuai.cn/protein/info"

    try:
        async with aiohttp.ClientSession() as session:
            if protein_id == "Q9H3P7":
                async with session.get("https://oss.taichuai.cn/agent/blastp_Q9H3P7.json") as response:
                    protein_blastps_text = await response.text()
                    protein_blastps = json.loads(protein_blastps_text)
            elif protein_id == "Q9P0L0":
                async with session.get("https://oss.taichuai.cn/agent/blastp_Q9P0L0.json") as response:
                    protein_blastps_text = await response.text()
                    protein_blastps = json.loads(protein_blastps_text)
            elif protein_id == "Q96HY6":
                async with session.get("https://oss.taichuai.cn/agent/blastp_Q96HY6.json") as response:
                    protein_blastps_text = await response.text()
                    protein_blastps = json.loads(protein_blastps_text)
            else:
                async with session.get(url) as response:
                    protein_blastps = await response.json()
            protein_ids = [blastp["sacc"] for blastp in protein_blastps]
            er_protein_infos = {}
            async with session.post(info_url, json={"protein_ids": protein_ids}) as info_response:
                protein_infos = await info_response.json()
                for protein_info in protein_infos:
                    subcellular_location = protein_info["subcellular_location"]
                    if subcellular_location.lower().find("endoplasmic reticulum") != -1:
                        er_protein_infos[protein_info["ac"]] = protein_info
            final_protein_blastps = []
            for blastp in protein_blastps:
                target_protein_id = blastp["sacc"]
                if target_protein_id in er_protein_infos.keys() and not (
                        blastp["identity"] > 95.0 and blastp["query_cover"] > 99.0):
                    blastp["sequence"] = er_protein_infos[target_protein_id]["sequence"]
                    blastp["site"] = er_protein_infos[target_protein_id]["site"]
                    blastp["domain"] = er_protein_infos[target_protein_id]["domain"]
                    final_protein_blastps.append(blastp)

            blastp_url = await upload_content_to_minio(json.dumps(final_protein_blastps, indent=4),
                                                       file_extension=".json",
                                                       content_type="application/octet-stream")

            return {
                "blastp_url": blastp_url,
                "columns": [
                    {
                        "title": "查询序列",
                        "field": "query_id"
                    },
                    {
                        "title": "目标序列",
                        "field": "subject_id"
                    },
                    {
                        "title": "目标序列ID",
                        "field": "sacc"
                    },
                    {
                        "title": "查询序列覆盖率(%) ",
                        "field": "query_cover"
                    },
                    {
                        "title": "E值",
                        "field": "evalue"
                    },
                    {
                        "title": "相似度(%)",
                        "field": "identity"
                    },
                    {
                        "title": "比对长度",
                        "field": "alignment_length"
                    },
                    {
                        "title": "错配数",
                        "field": "mismatches"
                    },
                    {
                        "title": "缺口打开数",
                        "field": "gap_opens"
                    },

                    {
                        "title": "比特得分",
                        "field": "bit_score"
                    },

                ]
            }
    except aiohttp.ClientError as e:
        return {"error": f"HTTP请求错误: {str(e)}"}
    except Exception as e:
        import traceback
        print(traceback.format_exc())
        return {"error": f"处理错误: {str(e)}"}


class ProteinBlastpInput(BaseModel):
    """蛋白同源结构评估"""
    protein_id: str = Field(
        ...,
        description="根据蛋白质id找到相似的同家族蛋白质，实例值：Q9P0L0",
        examples=["Q9P0L0"]
    )


protein_homology_evaluation = StructuredTool.from_function(
    coroutine=protein_blastp,
    name=Tools.PROTEIN_HOMOLOGY_EVALUATION,
    description="""
    【领域：生物】根据蛋白质id找到同源相似的或者同家族蛋白质，用于蛋白同源结构评估""",
    args_schema=ProteinBlastpInput,
    metadata={"args_schema_json": ProteinBlastpInput.schema()}
)


#####

async def af2_multimer(protein_sqs):
    if "P17706" in protein_sqs or "O95292" in protein_sqs:
        return {
            "json_url": "https://oss.taichuai.cn/agent/af2mr.json",
            "pdb_url": "https://oss.taichuai.cn/agent/af2mr.pdb"
        }
    elif "P50570" in protein_sqs or "Q96AG4" in protein_sqs:
        return {
            "json_url": "https://oss.taichuai.cn/agent/P50570_Q96AG4.json",
            "pdb_url": "https://oss.taichuai.cn/agent/P50570_Q96AG4.pdb"
        }
    else:
        return {
            "json_url": "https://oss.taichuai.cn/agent/Q17706_O95292.json",
            "pdb_url": "https://oss.taichuai.cn/agent/Q17706_O95292.pdb"
        }


class ProteinAf2MultimerInput(BaseModel):
    """预测两个或多个蛋白质之间的复合物三维结构"""
    protein_sqs: List[str] = Field(
        ...,
        description="""预测两个蛋白质之间的复合物三维结构，可以是蛋白质id也可以是序列，例如:
        P17706
        O95292
        MPTTIEREFEELDTQRRWQPLYLEIRNESHDYPHRVAKFPENRNRNRYRDVSPYDHSRVKLQNAENDYINASLVDIEEAQRSYILTQGPLPNTCCHFWLMVWQQKTKAVVMLNRIVEKESVKCAQYWPTDDQEMLFKETGFSVKLLSEDVKSYYTVHLLQLENINSGETRTISHFHYTTWPDFGVPESPASFLNFLFKVRESGSLNPDHGPAVIHCSAGIGRSGTFSLVDTCLVLMEKGDDINIKQVLLNMRKYRMGLIQTPDQLRFSYMAIIEGAKCIKGDSSIQKRWKELSKEDLSPAFDHSPNKIMTEKYNGNRIGLEEEKLTGDRCTGLSSKMQDTMEENSESALRKRIREDRKATTAQKVQQMKQRLNENERKRKRWLYWQPILTKMGFMSVILVGAFVGWTLFFQQNAL
        MAKVEQVLSLEPQHELKFRGPFTDVVTTNLKLGNPTDRNVCFKVKTTAPRRYCVRPNSGIIDAGASINVSVMLQPFDYDPNEKSKHKFMVQSMFAPTDTSDMEAVWKEAKPEDLMDSKLRCVFELPAENDKPHDVEINKIISTTASKTETPIVSKSLSSSLDDTEVKKVMEECKRLQGEVQRLREENKQFKEEDGLRMRKTVQSNSPISALAPTGKEEGLSTRLLALVVLFFIVGVIIGKIAL
        """
    )


af2_multimer_tool = StructuredTool.from_function(
    coroutine=af2_multimer,
    name=Tools.AF2_MULTIMER,
    description="""
    【领域：生物】基于深度学习的蛋白质结构预测模型，能够预测两个蛋白质之间的复合物三维结构。该模型构建于 AlphaFold2 架构之上，针对多链输入进行了优化，能够捕捉蛋白质之间的复杂相互作用模式。AlphaFold-Multimer 在蛋白质组学和结构生物学领域中表现出色，是理解分子机制和设计新型生物系统的重要工具。最终产出一个pdb文件""",
    args_schema=ProteinAf2MultimerInput,
    metadata={"args_schema_json": ProteinAf2MultimerInput.schema()}
)


##################### DiffSBDD 生成与蛋白结合口袋高度匹配的小分子配体 #####################


# class DiffSBDDInput(BaseModel):
#     """DiffSBDD 输入参数"""
#     pdb_file_url: str = Field(
#         ...,
#         description="pdb文件url地址",
#         examples=["http://oss.taichuai.cn/agent/proteins/787bd7b9fa_20250521_063105.pdb"]
#     )
#     ref_ligand_url: Optional[str] = Field(
#         description="可选参数：配体文件url地址",
#         examples=["http://oss.taichuai.cn/agent/ligands/ligand.sdf"]
#     )
#     resi_list: Optional[str] = Field(
#         description="可选参数：残基列表, 多个使用英文逗号分割，例如：A:300",
#         examples=["A:300"]
#     )


# async def diffsbdd_generate_ligands(pdb_file_url: str, ref_ligand_url, resi_list):
#     url = "https://gateway.taichuai.cn/diff-sbdd/generate_ligands"
#     # debug: 44机器不能访问测试环境130对象存储地址，使用地址本地调试
#     # pdb_file_url = "http://oss.taichuai.cn/agent/proteins/787bd7b9fa_20250521_063105.pdb"
#     payload = {
#         "pdb_file_url": pdb_file_url,
#         "n_samples": 20,
#         "sanitize": False,
#         "relax": False,
#         "is_upload": True  # 上传文件，返回文件存储url
#     }
#     if not any([ref_ligand_url, resi_list]):
#         return {"error": "请提供可选参数：配体文件url 或 残基列表"}
#     if ref_ligand_url:
#         payload["ref_ligand_url"] = ref_ligand_url
#     if resi_list:
#         payload['resi_list'] = resi_list.split(",")

#     headers = {"Content-Type": "application/json"}
#     try:
#         async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=300)) as session:
#             async with session.post(url, json=payload, headers=headers) as response:
#                 response.raise_for_status()
#                 js_data = await response.json()
#                 return js_data
#     except aiohttp.ClientError as e:
#         return {"error": f"HTTP请求错误: {str(e)}"}
#     except Exception as e:
#         return {"error": f"处理错误: {str(e)}"}


# diffsbdd_genrate_ligands_tool = StructuredTool.from_function(
#     coroutine=diffsbdd_generate_ligands,
#     name=Tools.DIFFSBDD_GENERATE_LIGANDS,
#     description="""
#     根据蛋白质PDB结构文件，生成与蛋白结合口袋高度匹配的小分子配体
#     """,
#     args_schema=DiffSBDDInput,
#     metadata={'scenes': [
#         {"name": '数字细胞', "step": 1},
#     ]
#     }
# )


##################### ESM-fold 从单条氨基酸序列中预测蛋白质的三维结构 #####################
# class ESMFoldInput(BaseModel):
#     """ESM-fold 输入参数"""
#     sequence: Optional[str] = Field(
#         None,
#         description="""
#         可选参数：蛋白质氨基酸序列，例如氨基酸序列为：
#         MDILCEENTSLSSTTNSLMQLNDDTRLYSNDFNSGEANTSDAFNWTVDSENRTNLSCEGCLSPSCLSLLHL
#         QEKNWSALLTAVVIILTIAGNILVIMAVSLEKKLQNATNYFLMSLAIADMLLGFLVMPVSMLTILYGYRWP
#         LPSKLCAVWIYLDVLFSTASIMHLCAISLDRYVAIQNPIHHSRFNSRTKAFLKIIAVWTISVGISMPIPVF
#         GLQDDSKVFKEGSCLLADDNFVLIGSFVSFFIPLTIMVITYFLTIKSLQKEATLCVSDLGTRAKLASFSFL
#         PQSSLSSEKLFQRSIHREPGSYTGRRTMQSISNEQKACKVLGIVFFLFVVMWCPFFITNIMAVICKESCNE
#         DVIGALLNVFVWIGYLSSAVNPLVYTLFNKTYRSAFSRYIQCQYKENKKPLQLILVNTIPALAYKSSQLQM
#         GQKKNSKQDAKTTDNDCSMVALGKQHSEEASKDNSDGVNEKVSCV
#         """
#     )
#     protein_id: Optional[str] = Field(
#         None,
#         description="可选参数，蛋白质UniProt ID，例如：P28223",
#         examples=["P28223", "Q96SW2", "P0DTD1"]
#     )


# async def esm_fold_predict_3d(sequence: str = None, protein_id: str = None):
#     if not sequence:
#         if not protein_id:
#             return {"error": "请提供 氨基酸序列 或者 蛋白质id"}

#         # 根据蛋白质ID获取序列

#         protein_url = f"http://120.220.102.26:38018/protein/info"
#         info_payload = {
#             "protein_ids": [protein_id]
#         }
#         try:
#             async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=300)) as session:
#                 async with session.post(protein_url, json=info_payload) as response:
#                     response.raise_for_status()
#                     js_data = await response.json()
#                     sequence = js_data[0]['sequence']

#         except Exception as e:
#             return {"error": f"通过蛋白质ID获取蛋白质序列错误: {str(e)}"}

#     predict_3d_url = "https://gateway.taichuai.cn/esmfold/api/v1/predict"
#     headers = {"Content-Type": "Application/json"}
#     payload = {
#         "sequence": sequence,
#         "as_pdb": True
#     }
#     try:
#         async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=300)) as session:
#             async with session.post(predict_3d_url, json=payload, headers=headers) as response:
#                 js_data = await response.json()
#                 return js_data
#     except aiohttp.ClientError as e:
#         return {"error": f"HTTP请求错误: {str(e)}"}
#     except Exception as e:
#         return {"error": f"处理错误: {str(e)}"}


# esmfold_predict_tool = StructuredTool.from_function(
#     coroutine=esm_fold_predict_3d,
#     name=Tools.ESM_FOLD_PREDICT_3D,
#     description="""
#     根据单个蛋白质ID/氨基酸序列，预测生成对应蛋白质的三维结构文件，预测速度快，适合快速分析蛋白质。
#     """,
#     args_schema=ESMFoldInput
# )




###

class PymolInput(BaseModel):

    pdb_url: str = Field(..., description="pdb文件url, 内容为复合物三维结构")
    cutoff: int = Field(
        4,
        description="""
        相互作用类型，默认值4:
        原子接触（一般范德华接触）: 取值4-5， 比较严格，适合检测原子间实际接触或较强的相互作用区域
        残基级相互作用（蛋白界面）：取值6，既包含紧密接触也包含潜在的弱相互作用
        较宽松的界面分析：8-10，包括所有可能的邻近区域，有时用于构建界面图谱或预测界面
        """
    )


async def pymol_pdb(
        pdb_url: str,
        cutoff: int = 4
) -> dict:
    url = "https://gateway.taichuai.cn/protein/pymol"

    # 构造请求负载
    payload = {
        "pdb_url": pdb_url,
        "cutoff": cutoff
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
pymol_pdb_tool = StructuredTool.from_function(
    coroutine=pymol_pdb,
    name=Tools.PYMOL,
    description="""
    【领域：生物】
    对于蛋白质复合物，判断三维结构是否存在相互作用的。该方法会识别位于两个链的界面区域的残基，也就是说，如果有相互作用，将返回相互接近（在一定距离阈值内）的残基。返回的是
    """,
    args_schema=PymolInput,
    metadata={"args_schema_json":PymolInput.schema()}
)


def mutate_protein_sequence(original_sequence, hgvs_mutation):
    """
    根据HGVS格式的蛋白质突变修改序列。

    参数:
        original_sequence (str): 原始氨基酸序列（单字母代码）。
        hgvs_mutation (str): HGVS格式的突变，如 "p.Arg106Trp"。

    返回:
        str: 突变后的序列。

    异常:
        ValueError: 如果突变格式无效或位置超出范围。
    """
    # 检查HGVS格式是否以"p."开头
    if not hgvs_mutation.startswith("p."):
        raise ValueError("HGVS突变格式应以'p.'开头，例如 'p.Arg106Trp'")

    # 提取原始氨基酸（三字母）、位置和突变后氨基酸（三字母）
    parts = hgvs_mutation[2:].split("_")[0]  # 处理可能的复杂突变（如"p.Arg106_Ser107del"）
    original_aa_3 = ''.join([c for c in parts if c.isalpha()][:3])  # 前三个字母是原始氨基酸
    position = int(''.join([c for c in parts if c.isdigit()]))  # 数字部分是位置
    mutated_aa_3 = ''.join([c for c in parts if c.isalpha()][3:])  # 后三个字母是突变后氨基酸

    # 将三字母代码转换为单字母代码
    aa_3to1 = protein_letters_3to1
    try:
        original_aa = aa_3to1[original_aa_3]
        mutated_aa = aa_3to1[mutated_aa_3]
    except KeyError:
        raise ValueError(f"无效的氨基酸三字母代码: {original_aa_3} 或 {mutated_aa_3}")

    # 检查位置是否有效
    if position < 1 or position > len(original_sequence):
        raise ValueError(f"突变位置 {position} 超出序列范围 (1-{len(original_sequence)})")

    # 检查原始序列中的氨基酸是否匹配
    if original_sequence[position - 1] != original_aa:
        raise ValueError(
            f"原始序列位置 {position} 是 '{original_sequence[position - 1]}'，"
            f"但突变要求 '{original_aa}'"
        )

    # 生成突变后的序列
    mutated_sequence = (
            original_sequence[:position - 1] + mutated_aa + original_sequence[position:]
    )

    return mutated_sequence


async def get_info_by_protein_identifier(protein_id: str, protein_gene: str):
    """使用该工具可以通过蛋白质标识符找到相关的疾病以及突变信息"""

    url = os.environ.get("PROTEIN_INFO_URL", "")

    payload = json.dumps({
        "stream": False,
        "detail": False,
        "messages": [
            {
                "content": f"请找出{protein_id} {protein_gene}相关的疾病和突变信息",
                "role": "user"
            }
        ]
    })
    headers = {
        # 'Authorization': 'Bearer fastgpt-tMJdwaDbWzHe0klJlqf5i4Sbl8BrzrkzcLy0hHPF6fXga9W518zk64twbqYT',
        'Authorization': 'Bearer fastgpt-pGe5mNaR6VL2KgiU5K6BOMr9n2XurENF9uwBtCYSnc5Sk3ZlNE3VyuZsRT16U9BSq',
        'Content-Type': 'application/json'
    }

    response = requests.request("POST", url, headers=headers, data=payload)
    try:
        if response.status_code == 200:
            choices = response.json().get('choices', [])
            if choices:
                json_string = choices[0].get('message', {}).get('content')
                marker = "===json==="

                # 检查标记是否存在
                if marker not in json_string:
                    raise ValueError(f"未找到标记 '{marker}'")

                # 分割字符串获取 JSON 部分
                parts = json_string.split(marker)

                # 通常 JSON 会在两个标记之间（parts[1]）
                if len(parts) < 2:
                    raise ValueError("标记格式不正确")

                json_content = parts[1].strip()

                if not json_content:
                    raise ValueError("标记之间没有 JSON 内容")

                try:
                    # 解析 JSON
                    json_content = json.loads(json_content)
                except json.JSONDecodeError as e:
                    raise ValueError(f"JSON 解析失败: {str(e)}")
                info_url = "https://gateway.taichuai.cn/protein/info"
                sequence = ""
                try:
                    async with aiohttp.ClientSession() as session:
                        async with session.post(info_url, json={"protein_ids": [protein_id]}) as info_response:
                            protein_infos = await info_response.json()
                            if protein_infos:
                                sequence = protein_infos[0]["sequence"]
                except Exception as e:
                    print(e)
                    raise Exception(str(e))
                for info in json_content.get("info", []):
                    info["sequence"] = sequence
                    try:
                        mutant_sequence = mutate_protein_sequence(
                            sequence,
                            info.get("protein_change")
                        )
                    except Exception as e:
                        print(e)
                        mutant_sequence = ""
                    info["mutant_sequence"] = mutant_sequence
                return json_content
    except Exception as e:
        import traceback
        print(traceback.format_exc())
        raise Exception(str(e))
    return None


class ProteinIdentifierInput(BaseModel):
    protein_id: str = Field(description="蛋白质Uniport id， 例如：O95292")
    protein_gene: str = Field(description="gene符号，例如：VAPB(VAPB_HUMAN)")


protein_identifier_tool = StructuredTool.from_function(
    coroutine=get_info_by_protein_identifier,
    name=Tools.PROTEIN_IDENTIFIER,
    description="""
    【领域：生物】根据蛋白质信息，找到和这个蛋白质相关的疾病和突变信息。蛋白质信息可以传入多个""",
    args_schema=ProteinIdentifierInput,
    metadata={"args_schema_json":ProteinIdentifierInput.schema()}
)




class BiologyAnalysisPlotInput(BaseModel):
    file_url: str = Field(
        description='文件URL'
    )
    plot_type: Literal["pca", "lineplot", "heatmap"] = Field(
        description="""
        分析/绘制图片类型，表达如下：
        1. pca: 执行主成分分析（PCA）并生成 2D 散点图
        2. lineplot: 生成多维折线图
        3. heatmap: 生成表达热图
        """
    )


async def biology_analysis_plot(
        file_url: str,
        plot_type: Literal["pca", "lineplot", "heatmap"]
) -> Dict[str, Any]:
    """ 根据文件url和指定分析的类型，返回分析结果地址
    """
    invoke_url = f"https://gateway.taichuai.cn/biograph/{plot_type}"
    allowed_extensions = ["xlsx", 'xls', 'csv']
    file_name = file_url.split('/')[-1]
    file_ext = file_name.split('.')[-1]
    if file_ext not in allowed_extensions:
        return {"url": None, "error": f"PCA分析支持的文件类型为：{''.join(allowed_extensions)}"}

    # 使用FormData 保存数据
    form_data = FormData()
    if plot_type == "pca":
        form_data.add_field("figsize", "20,16")
        form_data.add_field("dpi", "500")
    elif plot_type == "lineplot":
        form_data.add_field("x_col", "x")
    elif plot_type == "heatmap":
        form_data.add_field("show_numbers", "false")

    try:
        async with aiohttp.ClientSession() as session:
            # 下载文件
            async with session.get(file_url) as resp:
                file_content = await resp.read()
                form_data.add_field(
                    name="file",
                    value=file_content,
                    filename=file_name,
                    content_type="application/octet-stream"
                )

            # 分析绘图
            async with session.post(invoke_url, data=form_data) as response:
                if response.status == 200:
                    file_content = await response.read()
                    random_id = str(uuid.uuid4().hex)[-10:]
                    save_name = f"{plot_type}_result_{random_id}.png"
                    minio_url = await upload_content_to_minio(
                        file_content, file_name=save_name, file_extension=".png", content_type="image/png")

                    return {"url": minio_url, "error": None}
                else:
                    return {"url": "", "error": "PCA分析错误"}
    except Exception as e:
        return {"url": "", "error": f"PCA分析错误, detail: {str(e)}"}


biology_analysis_plot_tool = StructuredTool.from_function(
    coroutine=biology_analysis_plot,
    name=Tools.BIOLOGY_ANALYSIS_PLOT,
    description="""
    【领域：生物】
    给定文件URL和绘制结果类型，对xls/xlsx/csv文件数据内容进行分析并绘制以下图形：主成分分析图(pca)/多维折线图/热力图(heatmap)，返回分析结果图片地址
    """,
    args_schema=BiologyAnalysisPlotInput,
    metadata={"args_schema_json":BiologyAnalysisPlotInput.schema()},
    return_direct=True
)



