"""
Sandbox文件同步管理器
适用于没有volume挂载的Sandbox容器,通过API同步文件

使用场景:
1. 当前方案: 通过API同步文件(适用于现有容器)
2. 未来升级: 可以迁移到volume挂载方案
"""
import logging
from pathlib import Path
from typing import Optional, List, Dict
from agent_sandbox import Sandbox

from workflow.config import SandboxConfig
from workflow.sandbox_manager import get_path_manager

logger = logging.getLogger(__name__)


class SandboxFileSyncer:
    """
    Sandbox文件同步器

    通过Sandbox API实现文件上传/下载,适用于没有volume挂载的场景
    """

    def __init__(self, base_url: str = None):
        """
        初始化同步器

        Args:
            base_url: Sandbox服务地址
        """
        self.base_url = base_url or SandboxConfig().base_url
        self.client = Sandbox(base_url=self.base_url)
        self.path_manager = get_path_manager()

        # 获取Sandbox的home目录
        try:
            context = self.client.sandbox.get_context()
            self.sandbox_home = context.home_dir  # 通常是 /home/gem
            logger.info(f"Sandbox home directory: {self.sandbox_home}")
        except Exception as e:
            logger.warning(f"Failed to get sandbox home dir: {e}, using default")
            self.sandbox_home = "/home/gem"

    def upload_file(
        self,
        local_path: str,
        sandbox_path: str,
        encoding: str = "auto"
    ) -> bool:
        """
        上传单个文件到Sandbox

        Args:
            local_path: 宿主机文件路径
            sandbox_path: Sandbox目标路径
            encoding: 编码方式 (auto/utf-8/base64)

        Returns:
            是否成功
        """
        try:
            local_file = Path(local_path)
            if not local_file.exists():
                logger.error(f"Local file not found: {local_path}")
                return False

            # 自动判断编码
            if encoding == "auto":
                ext = local_file.suffix.lower()
                text_exts = [".txt", ".md", ".csv", ".json", ".py", ".log", ".yaml", ".yml", ".sh"]
                encoding = "utf-8" if ext in text_exts else "base64"

            # 读取文件内容
            if encoding == "utf-8":
                content = local_file.read_text(encoding="utf-8")
            else:
                import base64
                content = base64.b64encode(local_file.read_bytes()).decode("utf-8")

            # 上传到Sandbox
            result = self.client.file.write_file(
                file=sandbox_path,
                content=content,
                encoding=encoding
            )

            logger.info(f"Uploaded: {local_path} → {sandbox_path}")
            return True

        except Exception as e:
            logger.error(f"Failed to upload file {local_path}: {e}")
            return False

    def download_file(
        self,
        sandbox_path: str,
        local_path: str
    ) -> bool:
        """
        从Sandbox下载单个文件

        Args:
            sandbox_path: Sandbox文件路径
            local_path: 宿主机目标路径

        Returns:
            是否成功
        """
        try:
            # 判断文件类型,决定使用哪种编码
            ext = Path(sandbox_path).suffix.lower()
            binary_exts = ['.png', '.jpg', '.jpeg', '.gif', '.pdf', '.zip', '.tar', '.gz', '.bz2']

            # 从Sandbox读取文件
            if ext in binary_exts:
                # 二进制文件使用base64编码
                result = self.client.file.read_file(file=sandbox_path, encoding='base64')
                content = result.data.content

                # 保存到本地
                local_file = Path(local_path)
                local_file.parent.mkdir(parents=True, exist_ok=True)

                import base64
                local_file.write_bytes(base64.b64decode(content))
            else:
                # 文本文件使用utf-8编码
                result = self.client.file.read_file(file=sandbox_path)
                content = result.data.content

                # 保存到本地
                local_file = Path(local_path)
                local_file.parent.mkdir(parents=True, exist_ok=True)
                local_file.write_text(content, encoding="utf-8")

            logger.info(f"Downloaded: {sandbox_path} → {local_path}")
            return True

        except Exception as e:
            logger.error(f"Failed to download file {sandbox_path}: {e}")
            return False

    def list_sandbox_directory(self, sandbox_path: str) -> List[str]:
        """
        列出Sandbox目录中的文件

        Args:
            sandbox_path: Sandbox目录路径

        Returns:
            文件名列表
        """
        try:
            # 使用简单的ls命令列出文件
            result = self.client.shell.exec_command(
                command=f"ls -1 {sandbox_path} 2>/dev/null || echo ''"
            )

            output = result.data.output.strip()
            if not output:
                return []

            files = [f for f in output.split('\n') if f and f != '']
            return files

        except Exception as e:
            logger.error(f"Failed to list directory {sandbox_path}: {e}")
            return []

    def sync_outputs_to_host(self, session_id: str) -> Dict[str, any]:
        """
        同步Sandbox的outputs目录到宿主机

        这是核心功能: 将Agent在sandbox中生成的文件同步到宿主机

        Args:
            session_id: 会话ID

        Returns:
            同步结果统计
        """
        paths = self.path_manager.get_session_paths(session_id)
        if not paths:
            paths = self.path_manager.create_session_dirs(session_id)

        sandbox_outputs_dir = f"{self.sandbox_home}/outputs"

        # 列出Sandbox outputs目录的文件
        files = self.list_sandbox_directory(sandbox_outputs_dir)

        stats = {
            "total": len(files),
            "success": 0,
            "failed": 0,
            "files": []
        }

        for filename in files:
            sandbox_file = f"{sandbox_outputs_dir}/{filename}"
            local_file = paths.outputs / filename

            if self.download_file(sandbox_file, str(local_file)):
                stats["success"] += 1
                stats["files"].append(filename)
            else:
                stats["failed"] += 1

        logger.info(
            f"Synced outputs for session {session_id}: "
            f"{stats['success']}/{stats['total']} files"
        )

        return stats

    def upload_to_sandbox_uploads(
        self,
        local_path: str,
        session_id: str
    ) -> Optional[str]:
        """
        上传文件到Sandbox的uploads目录

        Args:
            local_path: 宿主机文件路径
            session_id: 会话ID

        Returns:
            Sandbox中的文件路径,失败返回None
        """
        local_file = Path(local_path)
        if not local_file.exists():
            logger.error(f"File not found: {local_path}")
            return None

        # 同时保存到宿主机的uploads目录(备份)
        paths = self.path_manager.get_session_paths(session_id)
        if not paths:
            paths = self.path_manager.create_session_dirs(session_id)

        import shutil
        host_upload_file = paths.uploads / local_file.name
        shutil.copy2(local_file, host_upload_file)
        logger.info(f"Backed up to host: {host_upload_file}")

        # 上传到Sandbox
        sandbox_path = f"{self.sandbox_home}/uploads/{local_file.name}"

        if self.upload_file(str(local_file), sandbox_path):
            return sandbox_path
        else:
            return None

    def ensure_sandbox_directories(self) -> bool:
        """
        确保Sandbox中存在必要的目录

        Returns:
            是否成功
        """
        try:
            dirs = ["workspace", "uploads", "outputs"]
            for dir_name in dirs:
                cmd = f"mkdir -p {self.sandbox_home}/{dir_name}"
                self.client.shell.exec_command(command=cmd)

            logger.info("Ensured sandbox directories exist")
            return True

        except Exception as e:
            logger.error(f"Failed to create sandbox directories: {e}")
            return False

    def cleanup_sandbox_session(self, session_id: str) -> bool:
        """
        清理Sandbox中的session文件(可选)

        Args:
            session_id: 会话ID

        Returns:
            是否成功
        """
        try:
            # 清理outputs目录
            cmd = f"rm -rf {self.sandbox_home}/outputs/*"
            self.client.shell.exec_command(command=cmd)

            # 清理uploads目录
            cmd = f"rm -rf {self.sandbox_home}/uploads/*"
            self.client.shell.exec_command(command=cmd)

            logger.info(f"Cleaned up sandbox for session: {session_id}")
            return True

        except Exception as e:
            logger.error(f"Failed to cleanup sandbox: {e}")
            return False


# 全局单例
_syncer: Optional[SandboxFileSyncer] = None


def get_sandbox_syncer() -> SandboxFileSyncer:
    """获取全局同步器单例"""
    global _syncer
    if _syncer is None:
        _syncer = SandboxFileSyncer()
        _syncer.ensure_sandbox_directories()
    return _syncer
