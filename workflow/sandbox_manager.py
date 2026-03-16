"""
AIO Sandbox路径映射管理器
参考DeerFlow的虚拟路径映射机制,实现宿主机与sandbox的文件共享
"""
import os
import shutil
import logging
from pathlib import Path
from typing import Dict, Optional
from datetime import datetime, timedelta
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class SessionPaths:
    """Session路径配置"""
    session_id: str
    session_root: Path
    workspace: Path
    uploads: Path
    outputs: Path

    def to_dict(self) -> Dict[str, str]:
        """转换为字典格式"""
        return {
            "session_id": self.session_id,
            "session_root": str(self.session_root),
            "workspace": str(self.workspace),
            "uploads": str(self.uploads),
            "outputs": str(self.outputs)
        }


class SandboxPathManager:
    """
    Sandbox路径映射管理器

    功能:
    1. 管理session目录结构
    2. 生成Docker volume挂载配置
    3. 提供路径转换(宿主机路径 <-> sandbox路径)
    4. 定期清理过期session
    """

    # Sandbox内的固定路径 (映射到宿主机workflow目录)
    SANDBOX_HOME = "/home/work"
    SANDBOX_WORKSPACE = f"{SANDBOX_HOME}/workspace"
    SANDBOX_UPLOADS = f"{SANDBOX_HOME}/uploads"
    SANDBOX_OUTPUTS = f"{SANDBOX_HOME}/outputs"

    def __init__(self, base_dir: str = None):
        """
        初始化路径管理器

        Args:
            base_dir: 宿主机数据根目录,默认为项目根目录下的nexus_data
        """
        if base_dir is None:
            # 获取项目根目录 (workflow的上级目录)
            project_root = Path(__file__).parent.parent
            base_dir = project_root / "nexus_data"

        self.base_dir = Path(base_dir)
        self.sessions_dir = self.base_dir / "sessions"
        self.temp_dir = self.base_dir / "temp"

        # 确保基础目录存在
        self.sessions_dir.mkdir(parents=True, exist_ok=True)
        self.temp_dir.mkdir(parents=True, exist_ok=True)

    def create_session_dirs(self, session_id: str) -> SessionPaths:
        """
        创建session目录结构

        Args:
            session_id: 会话ID

        Returns:
            SessionPaths: 包含所有路径的配置对象
        """
        session_root = self.sessions_dir / session_id

        paths = SessionPaths(
            session_id=session_id,
            session_root=session_root,
            workspace=session_root / "workspace",
            uploads=session_root / "uploads",
            outputs=session_root / "outputs"
        )

        # 创建所有目录
        for path in [paths.workspace, paths.uploads, paths.outputs]:
            path.mkdir(parents=True, exist_ok=True)
            logger.info(f"Created directory: {path}")

        # 创建README说明文件
        readme_content = f"""# Session {session_id}

Created: {datetime.now().isoformat()}

## Directory Structure
- workspace/: Agent工作区,可读写临时文件
- uploads/: 用户上传的文件,Agent只读
- outputs/: 最终输出文件,Agent可写

## Sandbox Mapping
- Host: {paths.workspace} → Sandbox: {self.SANDBOX_WORKSPACE}
- Host: {paths.uploads} → Sandbox: {self.SANDBOX_UPLOADS}
- Host: {paths.outputs} → Sandbox: {self.SANDBOX_OUTPUTS}
"""
        (session_root / "README.md").write_text(readme_content)

        return paths

    def get_session_paths(self, session_id: str) -> Optional[SessionPaths]:
        """
        获取已存在的session路径

        Args:
            session_id: 会话ID

        Returns:
            SessionPaths或None(如果session不存在)
        """
        session_root = self.sessions_dir / session_id

        if not session_root.exists():
            logger.warning(f"Session directory not found: {session_id}")
            return None

        return SessionPaths(
            session_id=session_id,
            session_root=session_root,
            workspace=session_root / "workspace",
            uploads=session_root / "uploads",
            outputs=session_root / "outputs"
        )

    def get_docker_volume_config(self, session_id: str) -> Dict[str, str]:
        """
        生成Docker volume挂载配置

        Args:
            session_id: 会话ID

        Returns:
            Dict[宿主机路径, sandbox路径]

        Example:
            {
                "/home/user/nexus_data/sessions/abc123/workspace": "/home/gem/workspace",
                "/home/user/nexus_data/sessions/abc123/uploads": "/home/gem/uploads",
                "/home/user/nexus_data/sessions/abc123/outputs": "/home/gem/outputs"
            }
        """
        paths = self.get_session_paths(session_id)
        if not paths:
            paths = self.create_session_dirs(session_id)

        return {
            str(paths.workspace): self.SANDBOX_WORKSPACE,
            str(paths.uploads): self.SANDBOX_UPLOADS,
            str(paths.outputs): self.SANDBOX_OUTPUTS
        }

    def host_to_sandbox_path(self, host_path: str, session_id: str) -> Optional[str]:
        """
        将宿主机路径转换为sandbox路径

        Args:
            host_path: 宿主机路径
            session_id: 会话ID

        Returns:
            sandbox路径或None
        """
        paths = self.get_session_paths(session_id)
        if not paths:
            return None

        host_path_obj = Path(host_path)

        # 检查路径属于哪个目录
        try:
            if host_path_obj.is_relative_to(paths.workspace):
                rel_path = host_path_obj.relative_to(paths.workspace)
                return f"{self.SANDBOX_WORKSPACE}/{rel_path}"
            elif host_path_obj.is_relative_to(paths.uploads):
                rel_path = host_path_obj.relative_to(paths.uploads)
                return f"{self.SANDBOX_UPLOADS}/{rel_path}"
            elif host_path_obj.is_relative_to(paths.outputs):
                rel_path = host_path_obj.relative_to(paths.outputs)
                return f"{self.SANDBOX_OUTPUTS}/{rel_path}"
        except ValueError:
            pass

        return None

    def sandbox_to_host_path(self, sandbox_path: str, session_id: str) -> Optional[str]:
        """
        将sandbox路径转换为宿主机路径

        Args:
            sandbox_path: sandbox路径
            session_id: 会话ID

        Returns:
            宿主机路径或None
        """
        paths = self.get_session_paths(session_id)
        if not paths:
            return None

        # 检查路径属于哪个目录
        if sandbox_path.startswith(self.SANDBOX_WORKSPACE):
            rel_path = sandbox_path[len(self.SANDBOX_WORKSPACE):].lstrip("/")
            return str(paths.workspace / rel_path)
        elif sandbox_path.startswith(self.SANDBOX_UPLOADS):
            rel_path = sandbox_path[len(self.SANDBOX_UPLOADS):].lstrip("/")
            return str(paths.uploads / rel_path)
        elif sandbox_path.startswith(self.SANDBOX_OUTPUTS):
            rel_path = sandbox_path[len(self.SANDBOX_OUTPUTS):].lstrip("/")
            return str(paths.outputs / rel_path)

        return None

    def cleanup_old_sessions(self, days: int = 7) -> int:
        """
        清理超过指定天数的session目录

        Args:
            days: 保留天数

        Returns:
            清理的session数量
        """
        cutoff_time = datetime.now() - timedelta(days=days)
        cleaned_count = 0

        for session_dir in self.sessions_dir.iterdir():
            if not session_dir.is_dir():
                continue

            # 检查目录修改时间
            mtime = datetime.fromtimestamp(session_dir.stat().st_mtime)
            if mtime < cutoff_time:
                try:
                    shutil.rmtree(session_dir)
                    logger.info(f"Cleaned up old session: {session_dir.name}")
                    cleaned_count += 1
                except Exception as e:
                    logger.error(f"Failed to clean up {session_dir.name}: {e}")

        return cleaned_count

    def get_session_size(self, session_id: str) -> int:
        """
        获取session目录的总大小(字节)

        Args:
            session_id: 会话ID

        Returns:
            目录大小(字节)
        """
        paths = self.get_session_paths(session_id)
        if not paths:
            return 0

        total_size = 0
        for dirpath, dirnames, filenames in os.walk(paths.session_root):
            for filename in filenames:
                filepath = Path(dirpath) / filename
                total_size += filepath.stat().st_size

        return total_size

    def list_sessions(self) -> list[Dict[str, any]]:
        """
        列出所有session及其信息

        Returns:
            session信息列表
        """
        sessions = []

        for session_dir in self.sessions_dir.iterdir():
            if not session_dir.is_dir():
                continue

            mtime = datetime.fromtimestamp(session_dir.stat().st_mtime)
            size = self.get_session_size(session_dir.name)

            sessions.append({
                "session_id": session_dir.name,
                "created": mtime.isoformat(),
                "size_bytes": size,
                "size_mb": round(size / 1024 / 1024, 2)
            })

        return sorted(sessions, key=lambda x: x["created"], reverse=True)


# 全局单例
_path_manager: Optional[SandboxPathManager] = None


def get_path_manager() -> SandboxPathManager:
    """获取全局路径管理器单例"""
    global _path_manager
    if _path_manager is None:
        _path_manager = SandboxPathManager()
    return _path_manager

