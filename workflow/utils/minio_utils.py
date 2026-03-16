import hashlib
import io
from datetime import datetime
from datetime import timedelta
from typing import Union
from urllib.parse import urlsplit, urlunsplit

from minio import Minio
from minio.error import S3Error

from workflow.config import MinioConfig

file_types = {
    "default": "application/octet-stream",
    "jpg": "image/jpeg",
    "tiff": "image/tiff",
    "gif": "image/gif",
    "jfif": "image/jpeg",
    "png": "image/png",
    "tif": "image/tiff",
    "ico": "image/x-icon",
    "jpeg": "image/jpeg",
    "wbmp": "image/vnd.wap.wbmp",
    "fax": "image/fax",
    "net": "image/pnetvue",
    "jpe": "image/jpeg",
    "rp": "image/vnd.rn-realpix"
}


async def minio_bucket_url(bucket_name: str) -> str:
    if MinioConfig.minio_secure == "true":
        url = f"https://{MinioConfig.minio_url}/{bucket_name}"
    else:
        url = f"http://{MinioConfig.minio_url}/{bucket_name}"
    return url


async def remove_params_from_url(url):
    # 拆分 URL
    parts = urlsplit(url)
    # 重新组合 URL，忽略查询参数和片段
    clean_url = urlunsplit((parts.scheme, parts.netloc, parts.path, '', ''))
    return clean_url


async def upload_content_to_minio(
        content: Union[str, bytes],
        file_name: str = None,
        file_extension: str = None,
        content_type: str = "text/plain",
        no_expired: bool = True,
) -> str:
    """
    将文本串上传到 MinIO（流式上传，不写临时文件）并返回文件的 URL

    :param content: 要上传的文本内容
    :param file_name: 文件名
    :return: 文件的 URL
    """
    # MinIO 配置
    minio_url = MinioConfig.minio_url
    access_key = MinioConfig.minio_access_key
    secret_key = MinioConfig.minio_secret_key
    bucket_name = MinioConfig.minio_bucket_name
    secure = True if MinioConfig.minio_secure == "true" else False

    # 创建 MinIO 客户端
    minio_client = Minio(
        minio_url,
        access_key=access_key,
        secret_key=secret_key,
        secure=secure
    )

    # 生成唯一的文件名
    current_time = datetime.now()
    formatted_time = current_time.strftime("%Y%m%d/%H%M%S_")
    # file_name = formatted_time + file_name
    try:
        # 将文本转为字节流（如果是二进制数据，可以直接用 io.BytesIO）
        if isinstance(content, str):
            content_bytes = content.encode("utf-8")
        else:
            content_bytes = content
        data_stream = io.BytesIO(content_bytes)
        if file_name:
            file_name = formatted_time + file_name
        elif file_extension:
            md5hash = hashlib.md5(content_bytes)
            md5_str = md5hash.hexdigest()
            file_name = formatted_time + md5_str + file_extension
        else:
            md5hash = hashlib.md5(content_bytes)
            md5_str = md5hash.hexdigest()
            file_name = formatted_time + md5_str + ".txt"
        # 上传到 MinIO（使用 put_object 流式上传）
        minio_client.put_object(
            bucket_name,
            file_name,
            data_stream,
            length=len(content_bytes),
            content_type=content_type
        )

        file_url = minio_client.presigned_get_object(
            bucket_name,
            file_name,
            expires=timedelta(days=7)
        )
        if no_expired:
            file_url = await remove_params_from_url(file_url)
        return file_url

    except S3Error as e:
        print(f"MinIO 错误: {e}")
        raise
    except Exception as e:
        print(f"错误: {e}")
        raise


async def download_file_from_minio(file_url: str) -> bytes:
    """从MinIO下载文件（简化实现）"""
    # 这是一个简化的实现，实际应该使用MinIO客户端
    import aiohttp
    
    async with aiohttp.ClientSession() as session:
        async with session.get(file_url) as response:
            response.raise_for_status()
            return await response.read()
