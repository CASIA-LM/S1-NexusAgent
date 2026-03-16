import json
from typing import Any, Dict, Optional, Literal, List

import aiohttp
from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field,validator

from workflow.config import MassSpec
from workflow.const import Tools
from workflow.utils.minio_utils import upload_content_to_minio
from io import BytesIO
from typing import List, Any, Dict
import pickle

import os
from minio import Minio
from minio.error import S3Error
from datetime import datetime, timedelta
import httpx

import pymatgen.core as mg
from pydantic import BaseModel, Field
from pymatgen.ext.matproj import MPRester
from pymatgen.io.cif import CifWriter
from pymatgen.core.structure import Structure, Composition, Element
from pymatgen.symmetry.analyzer import SpacegroupAnalyzer
from pymatgen.analysis.phase_diagram import PhaseDiagram
from pymatgen.entries.computed_entries import ComputedEntry




#### v2.0
class MatterGenInput(BaseModel):
    batch_size: Optional[int] = Field(
        default=4,
        description='批量生成数量，默认 4；数量越大耗时越久。'
    )
    batch: Optional[int] = Field(
        default=1,
        description='生成批次数，默认 1；倍数越大耗时越久。'
    )
    chemical_system: Optional[str] = Field(
        None,
        description=(
            "化学体系，例如 'W-Co' 或 'Fe-O'。\n"
            "—— 可单独作为条件使用；\n"
            "—— 或与 energy_above_hull 联合使用。"
        )
    )
    space_group: Optional[int] = Field(
        None,
        description=(
            "空间群编号 (International Tables 编号)，例如 225 表示 Fm-3m。\n"
            "—— 仅可单独作为条件使用。"
        )
    )
    dft_mag_density: Optional[float] = Field(
        None,
        description=(
            "DFT 计算得到的磁性密度 (μB/Å³)，范围通常 0–1。\n"
            "—— 仅可单独作为条件使用；\n"
            "—— 或与 hhi_score 联合使用。"
        ),
        ge=0.0, le=1.0
    )
    hhi_score: Optional[float] = Field(
        None,
        description=(
            "Herfindahl–Hirschman 指数 (HHI)，反映材料组成分散度，范围 0–1。\n"
            "—— 只能与 dft_mag_density 联合使用。"
        ),
        ge=0.0, le=1.0
    )
    dft_band_gap: Optional[float] = Field(
        None,
        description=(
            "DFT 计算得到的带隙 (eV)，范围 ≥0。\n"
            "—— 仅可单独作为条件使用。"
        ),
        ge=0.0
    )
    ml_bulk_modulus: Optional[float] = Field(
        None,
        description=(
            "机器学习预测的体积模量 (GPa)，范围 ≥0。\n"
            "—— 仅可单独作为条件使用。"
        ),
        ge=0.0
    )
    energy_above_hull: Optional[float] = Field(
        None,
        description=(
            "材料相对于能量凸包的能量上浮 (eV/atom)。\n"
            "—— 仅可与 chemical_system 联合使用。"
        ),
        ge=0.0
    )

# ===== 调用协程 =====
async def matter_gen_coroutine(
    batch_size: int = 4,
    batch: int = 1,
    chemical_system: Optional[str] = None,
    space_group: Optional[int] = None,
    dft_mag_density: Optional[float] = None,
    hhi_score: Optional[float] = None,
    dft_band_gap: Optional[float] = None,
    ml_bulk_modulus: Optional[float] = None,
    energy_above_hull: Optional[float] = None
) -> Dict[str, Any]:
    """
    基于扩散模型的材料结构生成，根据用户提供的单属性或支持的联合属性，
    自动选择最合适的 fine-tuned 模型或基模型。
    支持的属性条件：
      - chemical_system
      - space_group
      - dft_mag_density
      - hhi_score (联合 dft_mag_density)
      - dft_band_gap
      - ml_bulk_modulus
      - energy_above_hull (联合 chemical_system)
    """
    # 1. 收集非空条件
    props: Dict[str, Any] = {}
    if chemical_system is not None:
        props['chemical_system'] = chemical_system
    if space_group is not None:
        props['space_group'] = space_group
    if dft_mag_density is not None:
        props['dft_mag_density'] = dft_mag_density
    if hhi_score is not None:
        props['hhi_score'] = hhi_score
    if dft_band_gap is not None:
        props['dft_band_gap'] = dft_band_gap
    if ml_bulk_modulus is not None:
        props['ml_bulk_modulus'] = ml_bulk_modulus
    if energy_above_hull is not None:
        props['energy_above_hull'] = energy_above_hull
    
    # 2. 模型选择与合法性检验
    SUPPORTED_MULTI = [
        {'chemical_system', 'energy_above_hull'},
        {'dft_mag_density', 'hhi_score'}
    ]
    if len(props) > 1:
        keyset = set(props.keys())
        if keyset in SUPPORTED_MULTI:
            if keyset == {'chemical_system', 'energy_above_hull'}:
                model_name = 'chemical_system_energy_above_hull'
            else:
                model_name = 'dft_mag_density_hhi_score'
        else:
            raise ValueError(
                f"不支持组合条件 {keyset}。\n"
                "仅支持：单属性，或 (chemical_system + energy_above_hull)，或 (dft_mag_density + hhi_score)。"
            )
    else:
        if 'chemical_system' in props:
            model_name = 'chemical_system'
        elif 'space_group' in props:
            model_name = 'space_group'
        elif 'dft_mag_density' in props:
            model_name = 'dft_mag_density'
        elif 'dft_band_gap' in props:
            model_name = 'dft_band_gap'
        elif 'ml_bulk_modulus' in props:
            model_name = 'ml_bulk_modulus'
        else:
            model_name = 'mattergen_base'

    # 3. 构造调用载荷
    payload = {
        'model_name': model_name,
        'batch_size': batch_size,
        'num_batches': batch,
        'properties_to_condition_on': props,
        'diffusion_guidance_factor': 2.0
    }

    invoke_url = 'https://gateway.taichuai.cn/mattergen/generate'
    headers = {'Content-Type': 'application/json'}
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(invoke_url, headers=headers, json=payload) as resp:
                resp.raise_for_status()
                result = await resp.json()
                if 'data' in result and 'generation_time' in result['data']:
                    del result['data']['generation_time']
                return result
    except aiohttp.ClientError as err:
        return {'error': f'HTTP 请求错误: {err}'}
    except Exception as exc:
        return {'error': f'生成过程中出错: {exc}'}


# ===== 工具定义 =====
matter_gen_tool = StructuredTool.from_function(
    coroutine=matter_gen_coroutine,
    name=Tools.MATTER_GEN,
    description="""
    【领域：材料科学】
基于扩散模型的无机材料结构生成工具，支持按多种物理或化学属性引导结构设计。
系统将根据用户提供的条件，自动选择最合适的 fine-tuned 模型或基模型进行结构生成。

支持的属性条件与对应模型包括：
- `chemical_system` → 使用模型：`chemical_system`
- `space_group` → 使用模型：`space_group`
- `dft_mag_density` → 使用模型：`dft_mag_density`
- `dft_band_gap` → 使用模型：`dft_band_gap`
- `ml_bulk_modulus` → 使用模型：`ml_bulk_modulus`
- `dft_mag_density` + `hhi_score` → 使用模型：`dft_mag_density_hhi_score`
- `chemical_system` + `energy_above_hull` → 使用模型：`chemical_system_energy_above_hull`

若未提供任何条件，则默认使用 `mattergen_base` 进行无条件生成。
    """,
    args_schema=MatterGenInput,
    metadata={"args_schema_json": MatterGenInput.schema()}
)


######################## MatterGen 材料生成评估 ##################################
# 未测试成功
from pydantic import BaseModel, Field
from typing import Optional, Dict, Any
import aiohttp

# ===== 参数输入模型 =====
class MatterEvaluateInput(BaseModel):
    structures_file_url: str = Field(
        ...,
        description="待评估材料结构的压缩文件 URL，支持 .zip（CIF 格式）或 .extxyz 格式。"
    )
    relax: Optional[bool] = Field(
        default=True,
        description="是否进行结构弛豫。若为 True，则调用 MatterSim 力场对结构进行几何优化。"
    )
    # structure_matcher: Optional[str] = Field(
    #     default="disordered",
    #     description="结构匹配器类型，用于去重与唯一性判定。可选项包括 'disordered'、'strict' 等，默认为 'disordered'。"
    # )
    # energies_path: Optional[str] = Field(
    #     default=None,
    #     description="若 relax=False，可提供预计算的能量文件路径（支持相对路径或 URL）。"
    # )
    # potential_load_path: Optional[str] = Field(
    #     default=None,
    #     description="指定自定义势能模型的加载路径，用于替换默认 MatterSim 力场。"

    # )

# ===== 工具主逻辑（异步协程）=====
async def matter_evaluate_coroutine(
    structures_file_url: str,
    relax: bool = True,
    #structure_matcher: str = "disordered",
    #energies_path: Optional[str] = None,
    #potential_load_path: Optional[str] = None
) -> Dict[str, Any]:
    """
    调用 MatterGen 后端评估接口，计算材料结构的稳定性、新颖性、唯一性等性能指标。
    """

    url = "https://gateway.taichuai.cn/mattergen/evaluate"
    payload: Dict[str, Any] = {
        "structures_url": structures_file_url,
        "relax": relax,
        "structure_matcher": "disordered"
    }

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload) as resp:
                resp.raise_for_status()
                return await resp.json()
    except aiohttp.ClientResponseError as e:
        return {"error": f"HTTP {e.status}: {e.message}, input_url: {structures_file_url}"}
    except aiohttp.ClientConnectionError as e:
        return {"error": f"连接错误: {str(e)}, input_url: {structures_file_url}"}
    except Exception as e:
        return {"error": f"未知错误: {str(e)}, input_url: {structures_file_url}"}

# ===== 注册为 Agent 工具 =====
matter_evaluate_tool = StructuredTool.from_function(
    coroutine=matter_evaluate_coroutine,
    name=Tools.MATTER_EVAL,
    description="""
    【领域：材料科学】
    材料结构性能评估工具。支持上传 MatterGen 或用户自定义生成的晶体结构（压缩格式 URL），
    并可选择是否进行结构弛豫（Relaxation），自动计算结构稳定性、能量高低、新颖性、多样性、
    唯一性、几何相似度（RMSD）等关键材料性能指标。适用于材料生成、筛选与评估全流程。
    """,
    args_schema=MatterEvaluateInput,
    metadata={"args_schema_json": MatterEvaluateInput.schema()}
)



## 0703 ##

# -------- Helper functions --------
def save_to_pickle(data: Any, file_path: str) -> None:
    with open(file_path, 'wb') as f:
        pickle.dump(data, f)


def load_from_pickle(file_path: str) -> Any:
    with open(file_path, 'rb') as f:
        return pickle.load(f)


def create_cubic_lattice(lattice_parameter: float) -> bytes:
    lattice = mg.Lattice.cubic(lattice_parameter)
    return pickle.dumps(lattice)


def create_structure(lattice: Any, species: List[str], coords: List[List[float]]) -> bytes:
    struct = mg.Structure(lattice, species, coords)
    return pickle.dumps(struct)


def modify_structure(struct: Any, operation: str, target: List[Any]) -> bytes:
    if operation == 'make_supercell':
        struct.make_supercell(target[0])
    elif operation == 'delete':
        del struct[target[0]]
    elif operation == 'append':
        struct.append(target[0], target[1])
    elif operation == 'change':
        struct[-1] = target[0]
    elif operation == 'shift':
        struct[target[0]] = target[1]
    return pickle.dumps(struct)


def create_immutable_structure(struct: Any) -> bytes:
    immutable = mg.IStructure.from_sites(struct)
    return pickle.dumps(immutable)


######################## 通过晶格参数生成pkl文件 ##################################

# 测试成功
class CreateCubicLatticeInput(BaseModel):
    lattice_parameter: float = Field(
        ..., description="晶格常数，浮点数，定义立方晶格边长"
    )
async def create_cubic_lattice_coroutine(
    lattice_parameter: float
) -> Dict[str, Any]:
    """
    生成指定晶格常数的立方晶格，将其 pickle 后上传到 MinIO，
    并返回可下载的预签名 URL。

    """
  
    try:
        # 1. 构造 Lattice 对象并序列化到内存
        lattice = mg.Lattice.cubic(lattice_parameter)
        buffer = BytesIO()
        pickle.dump(lattice, buffer)
        buffer.seek(0)
        binary_data = buffer.getvalue()

        # 2. 生成文件名：带时间前缀 + 参数值
        now = datetime.now().strftime("%Y%m%d/%H%M%S")
        filename_base = f"cubic_lattice_{lattice_parameter}"
        file_name = f"{now}_{filename_base}.pkl"

        # 3. 上传到 MinIO
        #    注意：content_type 改为二进制流类型
        file_url = await upload_content_to_minio(
            content=binary_data,
            file_name=file_name,
            file_extension=".pkl",
            content_type="application/octet-stream",
            no_expired=True,
        )

        return {"Lattice_pickle_file_url": file_url}

    except S3Error as e:
        # MinIO SDK 抛出的异常，包含 HTTP 状态和错误码
        return {"error": f"MinIO 上传失败: {e.code} — {e.message}"}

    except Exception as e:
        # 其它任何异常
        return {"error": f"生成或上传过程出错: {str(e)}"}


create_cubic_lattice_tool = StructuredTool.from_function(
    coroutine=create_cubic_lattice_coroutine,
    name=Tools.CREATE_CUBIC_LATTICE,
    description="""
    【领域：材料科学】
    创建一个指定晶格常数的立方晶格，返回其pickle文件URL。
    参数:
      - lattice_parameter: 晶格常数，边长。
    """,
    args_schema=CreateCubicLatticeInput,
    metadata={"args_schema_json": CreateCubicLatticeInput.schema()}
)



######################## 对pkl文件进行 species、coords参数输入，返回新的pkl文件 #######################
# 测试成功
# 1. CreateStructure Tool
class CreateStructureInput(BaseModel):
    Lattice_pickle_file_url: str = Field(
        ..., description="上传的 Lattice pickle 文件 URL，如果上一个tool,例如”create_cubic_lattice_tool“输出的Lattice pickle 文件 URL，则使用该url作为输入"
    )
    species: List[str] = Field(
        ..., description="元素列表，例如 ['Fe', 'O']"
    )
    coords: List[List[float]] = Field(
        ..., description="分数坐标列表，对应元素位置"
    )

async def create_structure_coroutine(
    Lattice_pickle_file_url: str,
    species: List[str],
    coords: List[List[float]]
) -> Dict[str, Any]:
    """
    从 Lattice pickle 文件 URL、元素列表和坐标生成 Structure，
    pickle 序列化后上传到 MinIO 并返回预签名 URL。
    """
    try:
        # 下载 lattice
        async with aiohttp.ClientSession() as session:
            async with session.get(Lattice_pickle_file_url) as resp:
                resp.raise_for_status()
                lattice_data = await resp.read()
        lattice = pickle.loads(lattice_data)

        # 生成 structure 并序列化
        struct_binary = create_structure(lattice, species, coords)
        buffer = BytesIO(struct_binary)
        buffer.seek(0)
        data = buffer.getvalue()

        # 构造文件名
        now = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename_base = f"structure_{now}"
        file_name = f"{filename_base}.pkl"

        # 上传并获取 URL
        file_url = await upload_content_to_minio(
            content=data,
            file_name=file_name,
            file_extension=".pkl",
            content_type="application/octet-stream",
            no_expired=True,
        )
        return {"structure_file_url": file_url}

    except S3Error as e:
        return {"error": f"MinIO 上传失败: {e.code} - {e.message}"}
    except Exception as e:
        return {"error": f"生成或上传 Structure 失败: {str(e)}"}

create_structure_tool = StructuredTool.from_function(
    coroutine=create_structure_coroutine,
    name=Tools.CREATE_STRUCTURE,
    description="""
    【领域：材料科学】
    从 Lattice pickle 文件 URL、元素列表和坐标生成 Structure，
    返回其 pickle 文件 URL。
    """,
    args_schema=CreateStructureInput,
    metadata={"args_schema_json": CreateStructureInput.schema()}
)



######################## 对pkl文件进行 操作，返回新的pkl文件 #######################
# 测试成功
class ModifyStructureInput(BaseModel):
    structure_url: str = Field(
        ..., description="Structure pickle 文件的 URL"
    )
    operation: str = Field(
        ..., description="操作类型: make_supercell, delete, append, change, shift"
    )
    target: List[Any] = Field(
        ..., description="操作参数列表"
    )

async def modify_structure_coroutine(
    structure_url: str,
    operation: str,
    target: List[Any]
) -> Dict[str, Any]:
    """
    修改 Structure 文件，通过 URL 下载并根据操作生成新结构，
    上传并返回新的 pickle 文件 URL。
    """
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(structure_url) as resp:
                resp.raise_for_status()
                struct_data = await resp.read()
        struct = pickle.loads(struct_data)

        new_binary = modify_structure(struct, operation, target)
        buffer = BytesIO(new_binary)
        buffer.seek(0)
        data = buffer.getvalue()

        now = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename_base = f"modified_structure_{operation}_{now}"
        file_name = f"{filename_base}.pkl"

        file_url = await upload_content_to_minio(
            content=data,
            file_name=file_name,
            file_extension=".pkl",
            content_type="application/octet-stream",
            no_expired=True,
        )
        return {"file_url": file_url}

    except S3Error as e:
        return {"error": f"MinIO 上传失败: {e.code} - {e.message}"}
    except Exception as e:
        return {"error": f"修改 Structure 失败: {str(e)}"}

modify_structure_tool = StructuredTool.from_function(
    coroutine=modify_structure_coroutine,
    name=Tools.MODIFY_STRUCTURE,
    description="""
    【领域：材料科学】
    修改 Structure 文件（通过其 URL），支持超胞、原子删除、添加、修改等，
    并返回修改后文件 URL。
    ⚠️ 注意：输入的 URL 必须是 *Structure* 类型的 pickle 文件，而不是 *cubic_lattice*。
    如果你当前拥有的是 cubic_lattice 类型，请先使用 `create_structure` 工具将其转换为 Structure 对象，再使用本工具进行后续处理。
    
    """,
    args_schema=ModifyStructureInput,
    metadata={"args_schema_json": ModifyStructureInput.schema()}
)



######################## 对pkl文件转换为不可变结构，返回新的pkl文件 #######################
class CreateImmutableStructureInput(BaseModel):
    structure_url: str = Field(
        ..., description="Structure pickle 文件的 URL"
    )

async def create_immutable_structure_coroutine(
    structure_url: str
) -> Dict[str, Any]:
    """
    将 Structure pickle 文件（通过 URL）转为不可变结构，
    上传并返回新的 pickle 文件 URL。
    """
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(structure_url) as resp:
                resp.raise_for_status()
                struct_data = await resp.read()
        struct = pickle.loads(struct_data)

        immutable_binary = create_immutable_structure(struct)
        buffer = BytesIO(immutable_binary)
        buffer.seek(0)
        data = buffer.getvalue()

        now = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename_base = f"immutable_structure_{now}"
        file_name = f"{filename_base}.pkl"

        file_url = await upload_content_to_minio(
            content=data,
            file_name=file_name,
            file_extension=".pkl",
            content_type="application/octet-stream",
            no_expired=True,
        )
        return {"file_url": file_url}

    except S3Error as e:
        return {"error": f"MinIO 上传失败: {e.code} - {e.message}"}
    except Exception as e:
        return {"error": f"生成 Immutable Structure 失败: {str(e)}"}

create_immutable_structure_tool = StructuredTool.from_function(
    coroutine=create_immutable_structure_coroutine,
    name=Tools.CREATE_IMMUTABLE_STRUCTURE,
    description="""
    【领域：材料科学】
    本工具用于将 Structure 类型的 pickle 文件（通过 HTTP(s) URL 提供）转换为不可变结构，并返回新的 pickle 文件 URL。
    
    ⚠️ 注意：输入的 URL 必须是 *Structure* 类型的 pickle 文件，而不是 *cubic_lattice*。
    如果你当前拥有的是 cubic_lattice 类型，请先使用 `create_structure` 工具将其转换为 Structure 对象，再使用本工具进行后续处理。
    """,
    args_schema=CreateImmutableStructureInput,
    metadata={"args_schema_json": CreateImmutableStructureInput.schema()}
)



######################## 输入材料id从 Materials Project 拉取结构，pkl文件 #######################

#测试成功（0705）

# ===== 输入参数模型 =====
class FetchAndSaveStructureInput(BaseModel):
    #api_key: str = Field(..., description="Materials Project 的 API Key")
    material_id: str = Field(..., description="材料 ID，例如 mp-149")


# ===== 工具主逻辑（异步协程）=====
async def fetch_and_save_structure_coroutine(
    material_id: str
) -> Dict[str, str]:
    """
    从 Materials Project 获取结构，并分别保存为 CIF 和 PKL 格式后上传，返回 URL。
    """
    try:
        # 1. 获取结构
        import os
        api_key = os.getenv("MP_API_KEY", "")
        with MPRester(api_key) as rester:
            structure: Structure = rester.get_structure_by_material_id(material_id)

        # 2. 序列化为 PKL
        pkl_buffer = BytesIO()
        pickle.dump(structure, pkl_buffer)
        pkl_buffer.seek(0)
        pkl_data = pkl_buffer.getvalue()

        # 3. 写出为 CIF 格式字符串 -> 编码为 
        # from io import StringIO
        # cif_io = StringIO()
        # CifWriter(structure).write_file(cif_io)
        # cif_string = cif_io.getvalue()
        # cif_data = cif_string.encode("utf-8")

        # 4. 构造文件名
        now = datetime.now().strftime("%Y%m%d/%H%M%S")
        pkl_file_name = f"{now}_{material_id}.pkl"
        #cif_file_name = f"{now}_{material_id}.cif"

        # 5. 上传两个文件到 MinIO
        pkl_url = await upload_content_to_minio(
            content=pkl_data,
            file_name=pkl_file_name,
            file_extension=".pkl",
            content_type="application/octet-stream",
            no_expired=True,
        )

        # cif_url = await upload_content_to_minio(
        #     content=cif_data,
        #     file_name=cif_file_name,
        #     file_extension=".cif",
        #     content_type="application/octet-stream",
        #     no_expired=True,
        # )

        return {
            "structure_pickle_file_url": pkl_url,
            #"structure_cif_file_url": cif_url,
        }

    except Exception as e:
        return {"error": f"获取或保存结构失败: {str(e)}"}


# ===== 注册为 Agent 工具 =====
fetch_and_save_structure_tool = StructuredTool.from_function(
    coroutine=fetch_and_save_structure_coroutine,
    name=Tools.FETCH_AND_SAVE_STRUCTURE,
    description="""
    【领域：材料科学】
    从 Materials Project 拉取结构（通过 API Key 和材料 ID），
    并分别生成.pkl 文件，上传后返回两个文件的下载 URL。
    参数:
      - material_id: 材料 ID，例如 mp-149。
    返回:
      - structure_pickle_file_url: 结构的 pickle 文件下载 URL。
    """,
    args_schema=FetchAndSaveStructureInput,
    metadata={"args_schema_json": FetchAndSaveStructureInput.schema()}
)

######################## 对称性分析工具 #######################
# 测试成功
class AnalyzeSymmetryInput(BaseModel):
    structure_pickle_file_url: str = Field(
        ..., description="结构对象 pickle 文件的预签名 URL"
    )

async def analyze_symmetry_coroutine(
    structure_pickle_file_url: str
) -> dict:
    """
    下载并加载 Structure pickle 文件，分析其空间群符号并返回结果。
    """
    try:
        # 1. 下载 pickle 文件
        async with httpx.AsyncClient() as client:
            resp = await client.get(structure_pickle_file_url)
            resp.raise_for_status()
        structure = pickle.loads(resp.content)

        # 2. 对称性分析
        finder = SpacegroupAnalyzer(structure)
        space_group_symbol = finder.get_space_group_symbol()

        # 3. 返回分析结果
        return {"space_group_symbol": space_group_symbol}

    except httpx.HTTPError as e:
        return {"error": f"下载结构文件失败: {e}"}
    except Exception as e:
        return {"error": f"对称性分析失败: {e}"}


analyze_symmetry_tool = StructuredTool.from_function(
    coroutine=analyze_symmetry_coroutine,
    name=Tools.ANALYZE_SYMMETRY,
    description="""
    【领域：材料科学】
    分析给定晶体结构的对称性，返回空间群符号。
    参数:
      - structure_pickle_file_url: Structure 对象 pickle 文件的预签名 URL。
    """,
    args_schema=AnalyzeSymmetryInput,
    metadata={"args_schema_json": AnalyzeSymmetryInput.schema()}
)




########################  获取组合物属性工具 #######################
# 测试成功
class GetCompositionPropertiesInput(BaseModel):
    composition_str: str = Field(
        ..., description="化学式字符串，如 'Fe2O3' 或 'LiFePO4'"
    )
    element_str: str = Field(
        ..., description="化学式中关注的元素符号，如 'Fe'、'O' 等"
    )

async def get_composition_properties_coroutine(
    composition_str: str,
    element_str: str
) -> Dict[str, Any]:
    """
    读取给定的化学式，计算并返回：
      - 总分子量 (weight)
      - 指定元素的摩尔数 (amount_of_element)
      - 指定元素的摩尔分数 (atomic_fraction)
      - 指定元素的质量分数 (weight_fraction)
    """
    try:
        comp = Composition(composition_str)
        props = {
            "weight": comp.weight,
            "amount_of_element": comp.get_atomic_fraction(element_str) * comp.num_atoms,  # 或直接 comp[element_str]
            "atomic_fraction": comp.get_atomic_fraction(element_str),
            "weight_fraction": comp.get_wt_fraction(element_str)
        }
        return props

    except Exception as e:
        return {"error": f"计算组合物属性失败: {str(e)}"}


get_composition_properties_tool = StructuredTool.from_function(
    coroutine=get_composition_properties_coroutine,
    name=Tools.GET_COMPOSITION_PROPERTIES,
    description="""
    【领域：材料科学】
    计算指定化学式中某元素的：
      - 总分子量 (weight)
      - 摩尔数 (amount_of_element)
      - 原子分数 (atomic_fraction)
      - 质量分数 (weight_fraction)
    参数:
      - composition_str: 化学式字符串
      - element_str: 关注的元素符号
    """,
    args_schema=GetCompositionPropertiesInput,
    metadata={"args_schema_json":GetCompositionPropertiesInput.schema()} 
)


########################  获取原子质量工具  #######################
# 测试成功
class GetAtomicMassInput(BaseModel):
    element_str: str = Field(
        ..., description="元素符号，如 'Fe'、'Li'、'O' 等"
    )

async def get_atomic_mass_coroutine(
    element_str: str
) -> Dict[str, Any]:
    """
    返回指定元素的原子质量（atomic_mass）。
    """
    try:
        elem = Element(element_str)
        return {"atomic_mass": elem.atomic_mass}

    except Exception as e:
        return {"error": f"获取原子质量失败: {str(e)}"}


get_atomic_mass_tool = StructuredTool.from_function(
    coroutine=get_atomic_mass_coroutine,
    name=Tools.GET_ATOMIC_MASS,
    description="""
    【领域：材料科学】
    获取指定元素的原子质量。
    参数:
      - element_str: 元素符号
    """,
    args_schema=GetAtomicMassInput,
    metadata={"args_schema_json": GetAtomicMassInput.schema()}
)


########################  创建 PhaseDiagram 工具   #######################
# 测试成功
class CreatePhaseDiagramInput(BaseModel):
    entries_pickle_file_url: str = Field(
        ..., description="ComputedEntry 列表的 pickle 文件预签名 URL"
    )

async def create_phase_diagram_coroutine(
    entries_pickle_file_url: str
) -> Dict[str, Any]:
    """
    下载 ComputedEntry 列表 pickle，构造 PhaseDiagram，
    pickle 后上传到 MinIO，并返回预签名 URL。
    """
    try:
        # 1. 下载 entries pickle
        async with httpx.AsyncClient() as client:
            resp = await client.get(entries_pickle_file_url)
            resp.raise_for_status()
        entries: list[ComputedEntry] = pickle.loads(resp.content)

        # 2. 构建 PhaseDiagram
        phase_diagram = PhaseDiagram(entries)

        # 3. 序列化到内存
        buffer = BytesIO()
        pickle.dump(phase_diagram, buffer)
        buffer.seek(0)
        data = buffer.getvalue()

        # 4. 生成文件名
        now = datetime.now().strftime("%Y%m%d/%H%M%S")
        filename = f"{now}_phase_diagram.pkl"

        # 5. 上传到 MinIO
        file_url = await upload_content_to_minio(
            content=data,
            file_name=filename,
            file_extension=".pkl",
            content_type="application/octet-stream",
            no_expired=True,
        )

        return {"phase_diagram_pickle_file_url": file_url}

    except S3Error as e:
        return {"error": f"MinIO 上传失败: {e.code} — {e.message}"}
    except httpx.HTTPError as e:
        return {"error": f"下载 entries 文件失败: {str(e)}"}
    except Exception as e:
        return {"error": f"创建 PhaseDiagram 失败: {str(e)}"}


create_phase_diagram_tool = StructuredTool.from_function(
    coroutine=create_phase_diagram_coroutine,
    name=Tools.CREATE_PHASE_DIAGRAM,
    description="""
    【领域：材料科学】
    构建材料体系的相图（PhaseDiagram），并返回其 pickle 文件预签名 URL。

    ✅ 调用条件：
      - 输入必须是 **ComputedEntry 列表的 pickle 文件**；
      - 每个 entry 必须包含能量（energy）和化学组成（composition）信息；
      - 不支持结构（Structure）、晶格（Lattice）、单个 entry 等类型。

    ❌ 错误示例：
      - 结构结构的 pickle 文件（如 mp-149.pkl）；
      - CIF 文件或 Lattice 对象；

    参数说明：
      - entries_pickle_file_url: 包含多个 ComputedEntry 的 pickle 文件的 URL（通常由 Materials Project API 获取或用户手动构造）。

    返回值：
      - phase_diagram_pickle_file_url: 相图对象的 pickle 文件下载链接。
    """,
    args_schema=CreatePhaseDiagramInput,
    metadata={"args_schema_json": CreatePhaseDiagramInput.schema()}
)




########################  获取 E_above_hull 工具   #######################
# 测试成功
# ===== 输入参数模型 =====
class GetEAboveHullInput(BaseModel):
    phase_diagram_pickle_file_url: str = Field(
        ..., description="PhaseDiagram 对象 pickle 文件的预签名 URL"
    )
    entry_pickle_file_url: str = Field(
        ..., description="ComputedEntry 对象 pickle 文件的预签名 URL"
    )

# ===== 工具实现 =====
async def get_e_above_hull_coroutine(
    phase_diagram_pickle_file_url: str,
    entry_pickle_file_url: str
) -> Dict[str, Any]:
    """
    下载 PhaseDiagram 和 ComputedEntry（或条目列表）的 pickle，
    如果加载到的是列表，将自动提取唯一或第一条 ComputedEntry，
    然后计算并返回该 Entry 相对于相图的 E_above_hull。
    """
    try:
        async with httpx.AsyncClient() as client:
            # 下载并反序列化相图
            pd_resp = await client.get(phase_diagram_pickle_file_url)
            pd_resp.raise_for_status()
            phase_diagram = pickle.loads(pd_resp.content)
            if not isinstance(phase_diagram, PhaseDiagram):
                raise TypeError(f"下载对象不是 PhaseDiagram: {type(phase_diagram)}")

            # 下载并反序列化 entry 或 entry 列表
            e_resp = await client.get(entry_pickle_file_url)
            e_resp.raise_for_status()
            loaded = pickle.loads(e_resp.content)

        # 处理列表情况
        if isinstance(loaded, list):
            # 如果列表中只有一个条目，或尽早匹配目标
            entries = [e for e in loaded if isinstance(e, ComputedEntry)]
            if not entries:
                raise TypeError("列表中不包含任何 ComputedEntry 对象")
            # 默认使用第一个条目
            entry = entries[0]
        else:
            entry = loaded

        if not isinstance(entry, ComputedEntry):
            raise TypeError(f"加载对象不是 ComputedEntry: {type(entry)}")

        # 计算 E_above_hull
        e_above = phase_diagram.get_e_above_hull(entry)
        return {"e_above_hull": float(e_above)}

    except httpx.HTTPError as http_err:
        return {"error": f"网络下载失败: {str(http_err)}"}
    except (TypeError, pickle.PickleError) as type_err:
        return {"error": f"数据解析失败: {str(type_err)}"}
    except Exception as exc:
        return {"error": f"计算 E_above_hull 时出错: {str(exc)}"}

# ===== 工具定义 =====
get_e_above_hull_tool = StructuredTool.from_function(
    coroutine=get_e_above_hull_coroutine,
    name=Tools.GET_E_ABOVE_HULL,
    description="""
    【领域：材料科学】
    计算给定 Entry 在相图中的 E_above_hull。
    参数:
      - phase_diagram_pickle_file_url: PhaseDiagram 对象的 pickle URL。
      - entry_pickle_file_url: ComputedEntry 对象的 pickle URL。
    返回:
      - e_above_hull: 计算得到的能量上浮值。
    """,
    args_schema=GetEAboveHullInput,
    metadata={"args_schema_json": GetEAboveHullInput.schema()}

)

########################  查询材料，拉取 ComputedEntry 格式pkl文件   #######################
# 测试成功
class FetchAndSaveEntriesInput(BaseModel):
    # api_key: str = Field(..., description="Materials Project 的 API Key")
    # 二选一，给出化学体系或单个材料 ID
    chemsys: str = Field(None, description="化学体系，例如 'Mn-Fe-O'")
    material_id: str = Field(None, description="材料 ID，例如 'mp-149'，优先级高于 chemsys")

# ===== 工具主逻辑（异步协程）=====
async def fetch_and_save_entries_coroutine(
    chemsys: str = None,
    material_id: str = None
) -> Dict[str, str]:
    """
    从 Materials Project 获取 ComputedEntry 列表，并分别保存为 PKL 格式后上传，返回 URL。
    - chemsys: 三元组或多元组化学体系字符串，如 'Mn-Fe-O'
    - material_id: 单个材料 ID，如 'mp-149'，会自动转换为对应的 entry 列表
    """
    # 1. 拉取 entries
    api_key = os.getenv("MP_API_KEY", "")
    with MPRester(api_key) as mpr:
        if material_id:
            # 单个材料，获取其 entry
            entries = mpr.get_entries(material_id)
        elif chemsys:
            # 化学体系，获取全部 entries
            entries = mpr.get_entries_in_chemsys(chemsys.split("-"))
        else:
            raise ValueError("必须提供 chemsys 或 material_id 中的一个。")

    # 2. 序列化为 PKL
    pkl_buffer = BytesIO()
    pickle.dump(entries, pkl_buffer)
    pkl_buffer.seek(0)
    pkl_data = pkl_buffer.getvalue()

    # 3. 构造文件名
    now = datetime.now().strftime("%Y%m%d/%H%M%S")
    pkl_file_name = f"{now}_{material_id or chemsys.replace('-', '')}_entries.pkl"

    # 4. 上传到 MinIO
    entries_url = await upload_content_to_minio(
        content=pkl_data,
        file_name=pkl_file_name,
        file_extension=".pkl",
        content_type="application/octet-stream",
        no_expired=True,
    )

    return {
        "entries_pickle_file_url": entries_url
    }
fetch_and_save_entries_tool = StructuredTool.from_function(
    coroutine=fetch_and_save_entries_coroutine,
    name=Tools.FETCH_AND_SAVE_ENTRIES,
    description="""
    【领域：材料科学】
    从 Materials Project 拉取 ComputedEntry 列表（可指定化学体系或单个材料 ID），
    并生成 .pkl 文件，上传后返回文件的下载 URL。
    参数:
      - chemsys: 化学体系字符串，如 'Mn-Fe-O'，或
      - material_id: 单个材料 ID，如 'mp-149'（优先使用 material_id）。
    返回:
      - entries_pickle_file_url: ComputedEntry 列表的 pickle 文件下载 URL。
    """,
    args_schema=FetchAndSaveEntriesInput,
    metadata={"args_schema_json": FetchAndSaveEntriesInput.schema()}
)
