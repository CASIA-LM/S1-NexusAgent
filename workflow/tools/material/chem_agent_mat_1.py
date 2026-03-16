# from pydantic import BaseModel, Field
# from typing import Dict, Any, List
# import logging
# import asyncio
# from unknown_science.tools.chemistry.utils import is_multiple_smiles, split_smiles,tanimoto,is_smiles, pubchem_query2smiles
# from langchain_core.tools import StructuredTool
# from unknown_science.const import Tools
# import requests, re, pkg_resources, pandas as pd
# from unknown_science.utils.minio_utils import upload_content_to_minio
# from pymatgen.core.composition import Composition
# from pymatgen.analysis.defects.core import Vacancy, Interstitial
# from minio.error import S3Error
# from pymatgen.core import Element as mg




# # ---------- 工具3 ----------
# class AnalyzeElementalCompositionInput(BaseModel):
#     composition_str: str = Field(
#         ..., description="化学式字符串，例如 'NaCl'、'CaCO3'、'LiFePO4'"
#     )

# # ---------- 工具主逻辑 ----------
# async def analyze_elemental_composition_coroutine(
#     composition_str: str
# ) -> Dict[str, Any]:
#     """
#     解析化学式字符串，输出元素组成及对应的数量。
#     """
#     try:
#         composition = Composition(composition_str)
#         elem_dict = composition.get_el_amt_dict()
#         return elem_dict
#     except Exception as e:
#         return {"error": f"元素组成分析失败: {str(e)}"}

# # ---------- 工具封装 ----------
# analyze_elemental_composition_tool = StructuredTool.from_function(
#     coroutine=analyze_elemental_composition_coroutine,
#     name="ANALYZE_ELEMENTAL_COMPOSITION",
#     description="""
#     【领域：材料科学】
#     对给定化学式进行元素组成分析，返回各元素的数量。
#     功能:
#       - 输入化学式 (composition_str)，如 'NaCl'、'CaCO3'、'LiFePO4'
#       - 输出一个字典，键为元素符号，值为元素个数
#     应用场景:
#       - 材料化学式解析
#       - 元素比例计算
#       - 下游性质预测工具输入准备
#     参数:
#       - composition_str: 化学式字符串，例如 'NaCl'、'CaCO3'、'LiFePO4'
#     """,
#     args_schema=AnalyzeElementalCompositionInput,
#     metadata={"args_schema_json": AnalyzeElementalCompositionInput.schema()}
# )


# # ===== 输入参数定义 =====
# class CreateDefectInput(BaseModel):
#     structure_pickle_file_url: str = Field(
#         ..., description="上传的 Structure pickle 文件 URL，例如上一个工具（如 create_structure_tool）的输出结果 URL"
#     )
#     defect_type: str = Field(
#         ..., description="缺陷类型，可选: 'vacancy'（空位缺陷） 或 'interstitial'（间隙原子缺陷）"
#     )
#     site_index: int | None = Field(
#         None, description="当 defect_type='vacancy' 时必填，表示要移除的原子在结构中的索引位置"
#     )
#     element_str: str | None = Field(
#         None, description="当 defect_type='interstitial' 时必填，表示间隙原子的化学元素符号，例如 'Li' 或 'O'"
#     )
#     coords: List[float] | None = Field(
#         None, description="当 defect_type='interstitial' 时必填，表示间隙原子的坐标，例如 [0.25, 0.25, 0.25]"
#     )


# # ===== 协程函数实现 =====
# async def create_defect_coroutine(
#     structure_pickle_file_url: str,
#     defect_type: str,
#     site_index: int = None,
#     element_str: str = None,
#     coords: List[float] = None
# ) -> Dict[str, Any]:
#     """
#     从结构 pickle 文件 URL 创建缺陷（Vacancy 或 Interstitial），
#     并将结果序列化上传至 MinIO，返回预签名下载 URL。
#     """
#     try:
#         # 下载结构 pickle 文件
#         async with aiohttp.ClientSession() as session:
#             async with session.get(structure_pickle_file_url) as resp:
#                 resp.raise_for_status()
#                 struct_data = await resp.read()
#         structure = pickle.loads(struct_data)

#         # 构造缺陷
#         if defect_type == "vacancy":
#             if site_index is None:
#                 raise ValueError("site_index 必须在 vacancy 模式下提供")
#             site = structure[site_index]
#             defect = Vacancy(structure, site)

#         elif defect_type == "interstitial":
#             if element_str is None or coords is None:
#                 raise ValueError("interstitial 模式下必须提供 element_str 和 coords")
#             defect = Interstitial(structure, element_str, coords)

#         else:
#             raise ValueError("defect_type 必须是 'vacancy' 或 'interstitial'")

#         # 序列化为 pickle
#         defect_binary = pickle.dumps(defect)
#         buffer = BytesIO(defect_binary)
#         buffer.seek(0)
#         data = buffer.getvalue()

#         # 构造文件名
#         now = datetime.now().strftime("%Y%m%d_%H%M%S")
#         filename_base = f"defect_{defect_type}_{now}"
#         file_name = f"{filename_base}.pkl"

#         # 上传到 MinIO
#         file_url = await upload_content_to_minio(
#             content=data,
#             file_name=file_name,
#             file_extension=".pkl",
#             content_type="application/octet-stream",
#             no_expired=True,
#         )
#         return {"defect_file_url": file_url}

#     except S3Error as e:
#         return {"error": f"MinIO 上传失败: {e.code} - {e.message}"}
#     except Exception as e:
#         return {"error": f"缺陷创建失败: {str(e)}"}


# # ===== 工具封装 =====
# create_defect_tool = StructuredTool.from_function(
#     coroutine=create_defect_coroutine,
#     name=Tools.CREATE_DEFECT,
#     description="""
#     【领域：材料科学】
#     在给定的晶体结构中创建缺陷 (Defect)，支持两种模式:
#       1. vacancy (空位缺陷): 移除指定索引位置的原子。
#       2. interstitial (间隙原子缺陷): 在指定坐标处添加一个新元素。

#     输入:
#       - structure_pickle_file_url: 结构 pickle 文件的 URL
#       - defect_type: 缺陷类型 ('vacancy' 或 'interstitial')
#       - site_index: (vacancy 必填) 要移除原子的索引
#       - element_str: (interstitial 必填) 新增原子的化学符号
#       - coords: (interstitial 必填) 新增原子的坐标

#     输出:
#       - defect_file_url: 缺陷对象的 pickle 文件 URL
#     """,
#     args_schema=CreateDefectInput,
#     metadata={"args_schema_json": CreateDefectInput.schema()}
# )
