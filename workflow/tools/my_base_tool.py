import hashlib
import io
from datetime import datetime, timedelta
from typing import Union, Optional
from urllib.parse import urlsplit, urlunsplit

from pydantic import BaseModel, Field
from minio import Minio
from minio.error import S3Error
from langchain_core.tools import StructuredTool
from workflow.config import MinioConfig
from agent_sandbox import Sandbox, AsyncSandbox
from langchain_core.runnables import RunnableConfig


class MinioConfig:
    minio_url = MinioConfig.minio_url
    minio_access_key = MinioConfig.minio_access_key
    minio_secret_key = MinioConfig.minio_secret_key
    minio_bucket_name = MinioConfig.minio_bucket_name
    minio_secure = True if MinioConfig.minio_secure == "true" else False

async def remove_params_from_url(url: str) -> str:
    """从URL中移除查询参数和片段，用于获取非过期签名URL（如果no_expired=True）"""
    parts = urlsplit(url)
    clean_url = urlunsplit((parts.scheme, parts.netloc, parts.path, '', ''))
    return clean_url

# --- 工具输入模型 ---

class UploadContentToMinioInput(BaseModel):
    """
    MinIO文件上传工具输入参数模型
    """
    content: Union[str, bytes] = Field(..., description="需要上传的文件内容，可以是字符串（如文本）或字节串（如图片二进制数据）。")
    file_name: Optional[str] = Field(None, description="可选。指定上传到MinIO的完整文件名（包含扩展名）。如果提供，将覆盖默认的MD5/时间戳命名规则。")
    file_extension: Optional[str] = Field(None, description="可选。如果未提供file_name，可指定文件扩展名（例如：'.txt', '.png'）。将用于自动生成MD5/时间戳文件名。")
    content_type: str = Field("application/octet-stream", description="文件的MIME类型（Content-Type），例如：'text/plain', 'image/png'。默认为'application/octet-stream'。")
    no_expired: bool = Field(True, description="是否返回非过期URL。如果为True，将移除预签名URL中的签名参数。默认True。")

# --- 工具函数 ---

async def upload_content_to_minio(
        content: Union[str, bytes],
        file_name: str = None,
        file_extension: str = None,
        content_type: str = "application/octet-stream",
        no_expired: bool = True,
) -> str:
    """
    【领域：文件】
    将文本或二进制内容流式上传到 MinIO 对象存储，并返回文件的可访问 URL。
    
    该工具适用于CodeAgent需要保存其生成的文本、代码文件、图片等内容，
    并向用户提供一个下载链接的场景。内容不会写入本地临时文件。

    :param content: 要上传的文本内容 (str) 或二进制内容 (bytes)。
    :param file_name: 可选。指定的文件名（包含扩展名）。如果提供，将使用此名称。
    :param file_extension: 可选。如果未提供file_name，可指定扩展名。
    :param content_type: 文件的 MIME 类型。
    :param no_expired: 是否尝试返回非过期（永久）URL (移除预签名参数)。
    :return: 上传后文件的可访问 URL (str)。
    :raises S3Error: MinIO操作失败时抛出。
    """
    # MinIO 配置
    minio_url = MinioConfig.minio_url
    access_key = MinioConfig.minio_access_key
    secret_key = MinioConfig.minio_secret_key
    bucket_name = MinioConfig.minio_bucket_name
    # 兼容 Minio url 端口号
    if ":" in minio_url:
        minio_host, minio_port = minio_url.split(":")
    else:
        minio_host = minio_url
        minio_port = None
        
    secure = True if MinioConfig.minio_secure == "true" else False

    # 创建 MinIO 客户端
    # 客户端初始化时，host不应该包含 http(s)://
    minio_client = Minio(
        minio_host if minio_port is None else minio_url,
        access_key=access_key,
        secret_key=secret_key,
        secure=secure
    )

    # 准备内容和文件名
    current_time = datetime.now()
    formatted_time = current_time.strftime("%Y%m%d/%H%M%S_")

    try:
        # 将内容转为字节流
        if isinstance(content, str):
            content_bytes = content.encode("utf-8")
        else:
            content_bytes = content
        data_stream = io.BytesIO(content_bytes)
        
        # 确定最终文件名
        if file_name:
            # 完整文件名，加上时间戳前缀以避免冲突
            final_file_name = formatted_time + file_name
        elif file_extension:
            # 使用MD5和扩展名生成文件名
            md5hash = hashlib.md5(content_bytes)
            md5_str = md5hash.hexdigest()
            # 确保扩展名以点开头
            if not file_extension.startswith("."):
                file_extension = "." + file_extension
            final_file_name = formatted_time + md5_str + file_extension
        else:
            # 默认使用.txt和MD5
            md5hash = hashlib.md5(content_bytes)
            md5_str = md5hash.hexdigest()
            final_file_name = formatted_time + md5_str + ".txt"

        # 检查 bucket 是否存在
        if not minio_client.bucket_exists(bucket_name):
            # 创建 bucket (在实际生产环境中可能不需要此步骤，取决于策略)
            minio_client.make_bucket(bucket_name)

        # 上传到 MinIO（使用 put_object 流式上传）
        minio_client.put_object(
            bucket_name,
            final_file_name,
            data_stream,
            length=len(content_bytes),
            content_type=content_type
        )
        
        # 生成预签名URL (默认7天过期)
        file_url = minio_client.presigned_get_object(
            bucket_name,
            final_file_name,
            expires=timedelta(days=7)
        )
        
        # 如果要求非过期URL，则移除签名参数
        if no_expired:
            file_url = await remove_params_from_url(file_url)
        
        return file_url

    except S3Error as e:
        print(f"MinIO 错误: {e}")
        raise ValueError(f"MinIO S3 操作失败: {e}")
    except Exception as e:
        print(f"上传过程中发生未知错误: {e}")
        raise RuntimeError(f"文件上传失败: {e}")

# --- 工具注册 (使用您的Agent框架所需的注册方式) ---

upload_content_tool = StructuredTool.from_function(
    coroutine=upload_content_to_minio,
    name="upload_content_to_minio", # 建议名称清晰表达功能
    description="""
    【领域：文件】将内容（文本或二进制）流式上传到 MinIO 对象存储，并返回文件的可访问 URL。
    适用于保存CodeAgent的输出文件（如生成的代码、报告、图片等），并提供给用户下载链接。
    
    示例 (上传生成的图片二进制数据):
    - **场景**: 将一个二进制图像数据（例如 PNG 格式）上传到 MinIO。
    - **输入**:
      content: <一个表示PNG图片内容的 Python bytes 变量，例如：`generated_image_bytes`>
      file_extension: ".png"
      content_type: "image/png"
      no_expired: True
    - **调用**:
      upload_content_to_minio(
          content=generated_image_bytes, 
          file_extension=".png", 
          content_type="image/png"
      )
    - **返回**: 
      "url"
""",
    args_schema=UploadContentToMinioInput,
    metadata={"args_schema_json":UploadContentToMinioInput.schema()}
)








