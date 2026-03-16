"""
Sandbox文件操作工具(集成路径映射和文件同步)
参考DeerFlow设计,提供宿主机和sandbox之间的文件操作

支持两种模式:
1. API同步模式: 通过Sandbox API上传/下载文件(当前使用)
2. Volume挂载模式: 直接文件系统访问(未来升级)
"""
import os
import shutil
import base64
import logging
from pathlib import Path
from typing import Optional
from pydantic import BaseModel, Field
from langchain_core.tools import StructuredTool
from agent_sandbox import Sandbox

from workflow.config import SandboxConfig
from workflow.sandbox_manager import get_path_manager
from workflow.sandbox_sync import get_sandbox_syncer
from workflow.utils.minio_utils import upload_content_to_minio

logger = logging.getLogger(__name__)

# Sandbox配置
sandbox_url = SandboxConfig().base_url


# ==================== 输入输出Schema ====================

class UploadFileToSandboxInput(BaseModel):
    """上传文件到sandbox的输入"""
    file_path: str = Field(
        description="宿主机上的文件路径"
    )
    session_id: str = Field(
        description="会话ID"
    )


class UploadFileToSandboxOutput(BaseModel):
    """上传文件到sandbox的输出"""
    sandbox_path: str = Field(
        description="文件在sandbox中的路径"
    )
    message: str = Field(
        description="操作结果消息"
    )


class SaveOutputFileInput(BaseModel):
    """保存输出文件的输入"""
    content: str = Field(
        description="文件内容"
    )
    filename: str = Field(
        description="文件名"
    )
    session_id: str = Field(
        description="会话ID"
    )
    upload_to_minio: bool = Field(
        default=False,
        description="是否同时上传到MinIO获取分享链接"
    )


class SaveOutputFileOutput(BaseModel):
    """保存输出文件的输出"""
    local_path: str = Field(
        description="宿主机本地路径"
    )
    sandbox_path: str = Field(
        description="sandbox中的路径"
    )
    minio_url: Optional[str] = Field(
        default=None,
        description="MinIO分享链接(如果启用)"
    )


class GetOutputFileInput(BaseModel):
    """获取输出文件的输入"""
    filename: str = Field(
        description="文件名"
    )
    session_id: str = Field(
        description="会话ID"
    )


class GetOutputFileOutput(BaseModel):
    """获取输出文件的输出"""
    content: str = Field(
        description="文件内容"
    )
    local_path: str = Field(
        description="宿主机本地路径"
    )


class SyncOutputsInput(BaseModel):
    """同步outputs目录的输入"""
    session_id: str = Field(
        description="会话ID"
    )


class SyncOutputsOutput(BaseModel):
    """同步outputs目录的输出"""
    total: int = Field(
        description="总文件数"
    )
    success: int = Field(
        description="成功同步的文件数"
    )
    files: list = Field(
        description="同步的文件列表"
    )


# ==================== 工具函数实现 ====================

async def upload_file_to_sandbox_v2(
    file_path: str,
    session_id: str
) -> dict:
    """
    上传文件到sandbox的uploads目录

    使用API同步模式: 通过Sandbox API上传文件

    Args:
        file_path: 宿主机文件路径
        session_id: 会话ID

    Returns:
        包含sandbox路径和消息的字典
    """
    syncer = get_sandbox_syncer()

    # 上传文件到sandbox
    sandbox_path = syncer.upload_to_sandbox_uploads(file_path, session_id)

    if sandbox_path:
        return {
            "sandbox_path": sandbox_path,
            "message": f"文件已上传到sandbox: {sandbox_path}"
        }
    else:
        return {
            "sandbox_path": "",
            "message": f"上传失败: {file_path}"
        }


async def save_output_file(
    content: str,
    filename: str,
    session_id: str,
    upload_to_minio: bool = False
) -> dict:
    """
    保存输出文件到outputs目录

    注意: 由于使用API同步模式,文件实际保存在sandbox中
    需要调用sync_outputs_to_host()来同步到宿主机

    Args:
        content: 文件内容
        filename: 文件名
        session_id: 会话ID
        upload_to_minio: 是否上传到MinIO

    Returns:
        包含路径信息的字典
    """
    path_manager = get_path_manager()
    syncer = get_sandbox_syncer()

    # 1. 保存到宿主机outputs目录(本地备份)
    paths = path_manager.get_session_paths(session_id)
    if not paths:
        paths = path_manager.create_session_dirs(session_id)

    try:
        output_file = paths.outputs / filename
        output_file.write_text(content, encoding='utf-8')
        local_path = str(output_file)
        sandbox_path = f"{syncer.sandbox_home}/outputs/{filename}"

        result = {
            "local_path": local_path,
            "sandbox_path": sandbox_path,
            "minio_url": None
        }

        logger.info(f"Saved output file: {local_path}")

        # 2. 可选: 上传到MinIO
        if upload_to_minio:
            try:
                minio_url = await upload_content_to_minio(
                    content=content,
                    file_name=filename
                )
                result["minio_url"] = minio_url
                logger.info(f"Uploaded to MinIO: {minio_url}")
            except Exception as e:
                logger.error(f"Failed to upload to MinIO: {e}")

        return result

    except Exception as e:
        logger.error(f"Failed to save output file: {e}")
        return {
            "local_path": "",
            "sandbox_path": "",
            "minio_url": None
        }


async def get_output_file(
    filename: str,
    session_id: str
) -> dict:
    """
    从outputs目录获取文件内容

    优先从宿主机读取,如果不存在则从sandbox同步

    Args:
        filename: 文件名
        session_id: 会话ID

    Returns:
        包含文件内容和路径的字典
    """
    path_manager = get_path_manager()
    syncer = get_sandbox_syncer()

    paths = path_manager.get_session_paths(session_id)
    if not paths:
        paths = path_manager.create_session_dirs(session_id)

    output_file = paths.outputs / filename

    # 如果本地文件不存在,尝试从sandbox同步
    if not output_file.exists():
        logger.info(f"File not found locally, syncing from sandbox: {filename}")
        sandbox_path = f"{syncer.sandbox_home}/outputs/{filename}"

        if syncer.download_file(sandbox_path, str(output_file)):
            logger.info(f"Synced file from sandbox: {filename}")
        else:
            return {
                "content": "",
                "local_path": str(output_file),
                "message": f"错误: 文件不存在 {filename}"
            }

    try:
        content = output_file.read_text(encoding='utf-8')
        return {
            "content": content,
            "local_path": str(output_file),
            "message": "成功读取文件"
        }

    except Exception as e:
        logger.error(f"Failed to read output file: {e}")
        return {
            "content": "",
            "local_path": str(output_file),
            "message": f"读取失败: {str(e)}"
        }


async def sync_sandbox_outputs(session_id: str) -> dict:
    """
    同步sandbox的outputs目录到宿主机

    这是关键功能: 将Agent在sandbox中生成的所有文件同步到宿主机

    Args:
        session_id: 会话ID

    Returns:
        同步统计信息
    """
    syncer = get_sandbox_syncer()

    try:
        stats = syncer.sync_outputs_to_host(session_id)
        return stats

    except Exception as e:
        logger.error(f"Failed to sync outputs: {e}")
        return {
            "total": 0,
            "success": 0,
            "failed": 1,
            "files": []
        }


# ==================== LangChain工具定义 ====================

sandbox_file_upload_tool_v2 = StructuredTool.from_function(
    coroutine=upload_file_to_sandbox_v2,
    name="upload_file_to_sandbox",
    description=(
        "上传宿主机文件到sandbox的uploads目录。"
        "文件将在sandbox中的/home/gem/uploads/目录下可访问。"
        "适用于需要在sandbox中处理本地文件的场景。"
    ),
    args_schema=UploadFileToSandboxInput,
    metadata={
        "args_schema_json": UploadFileToSandboxInput.model_json_schema(),
        "output_schema_json": UploadFileToSandboxOutput.model_json_schema(),
    },
)

sandbox_save_output_tool = StructuredTool.from_function(
    coroutine=save_output_file,
    name="save_output_file",
    description=(
        "保存文件到outputs目录。"
        "所有最终结果文件都应该保存到这里,宿主机可以直接访问。"
        "可选择同时上传到MinIO获取分享链接。"
    ),
    args_schema=SaveOutputFileInput,
    metadata={
        "args_schema_json": SaveOutputFileInput.model_json_schema(),
        "output_schema_json": SaveOutputFileOutput.model_json_schema(),
    },
)

sandbox_get_output_tool = StructuredTool.from_function(
    coroutine=get_output_file,
    name="get_output_file",
    description=(
        "从outputs目录读取文件内容。"
        "用于获取之前保存的输出文件。"
        "如果本地不存在,会自动从sandbox同步。"
    ),
    args_schema=GetOutputFileInput,
    metadata={
        "args_schema_json": GetOutputFileInput.model_json_schema(),
        "output_schema_json": GetOutputFileOutput.model_json_schema(),
    },
)

sandbox_sync_outputs_tool = StructuredTool.from_function(
    coroutine=sync_sandbox_outputs,
    name="sync_sandbox_outputs",
    description=(
        "同步sandbox的outputs目录到宿主机。"
        "在代码执行完成后调用此工具,将所有生成的文件同步到宿主机。"
        "这样宿主机就可以访问Agent生成的所有文件。"
    ),
    args_schema=SyncOutputsInput,
    metadata={
        "args_schema_json": SyncOutputsInput.model_json_schema(),
        "output_schema_json": SyncOutputsOutput.model_json_schema(),
    },
)
