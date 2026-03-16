"""
AIO Sandbox启动和管理工具
支持动态volume挂载和session管理
"""
import subprocess
import logging
from typing import Optional
from agent_sandbox import Sandbox

from workflow.config import SandboxConfig
from workflow.sandbox_manager import get_path_manager

logger = logging.getLogger(__name__)


class SandboxLauncher:
    """
    Sandbox启动器

    功能:
    1. 动态启动带volume挂载的sandbox容器
    2. 管理容器生命周期
    3. 提供sandbox客户端
    """

    def __init__(self, base_url: str = None):
        """
        初始化启动器

        Args:
            base_url: Sandbox服务地址,默认从配置读取
        """
        self.base_url = base_url or SandboxConfig().base_url
        self.path_manager = get_path_manager()

    def start_sandbox_with_session(
        self,
        session_id: str,
        container_name: str = None,
        port: int = 9001,
        image: str = "ghcr.io/agent-infra/sandbox:latest"
    ) -> bool:
        """
        启动带session挂载的sandbox容器

        Args:
            session_id: 会话ID
            container_name: 容器名称
            port: 宿主机端口
            image: Docker镜像

        Returns:
            是否启动成功
        """
        if container_name is None:
            container_name = f"nexus-sandbox-{session_id[:8]}"

        # 创建session目录
        paths = self.path_manager.create_session_dirs(session_id)

        # 构建docker run命令
        volume_mounts = self.path_manager.get_docker_volume_config(session_id)

        cmd = [
            "docker", "run",
            "--name", container_name,
            "--security-opt", "seccomp=unconfined",
            "--rm",  # 容器停止后自动删除
            "-d",  # 后台运行
            "-p", f"{port}:8080",
            "--shm-size", "2gb",
            "-e", "WORKSPACE=/home/gem",
            "-e", "TZ=Asia/Shanghai"
        ]

        # 添加volume挂载
        for host_path, sandbox_path in volume_mounts.items():
            cmd.extend(["-v", f"{host_path}:{sandbox_path}"])

        cmd.append(image)

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                check=True
            )
            container_id = result.stdout.strip()
            logger.info(f"Started sandbox container: {container_id[:12]}")
            logger.info(f"Session {session_id} mounted:")
            for host_path, sandbox_path in volume_mounts.items():
                logger.info(f"  {host_path} → {sandbox_path}")

            return True

        except subprocess.CalledProcessError as e:
            logger.error(f"Failed to start sandbox: {e.stderr}")
            return False

    def stop_sandbox(self, container_name: str) -> bool:
        """
        停止sandbox容器

        Args:
            container_name: 容器名称

        Returns:
            是否停止成功
        """
        try:
            subprocess.run(
                ["docker", "stop", container_name],
                capture_output=True,
                text=True,
                check=True
            )
            logger.info(f"Stopped sandbox container: {container_name}")
            return True

        except subprocess.CalledProcessError as e:
            logger.error(f"Failed to stop sandbox: {e.stderr}")
            return False

    def get_sandbox_client(self) -> Sandbox:
        """
        获取sandbox客户端

        Returns:
            Sandbox客户端实例
        """
        return Sandbox(base_url=self.base_url)

    def is_sandbox_running(self, container_name: str) -> bool:
        """
        检查sandbox容器是否运行

        Args:
            container_name: 容器名称

        Returns:
            是否运行中
        """
        try:
            result = subprocess.run(
                ["docker", "ps", "--filter", f"name={container_name}", "--format", "{{.Names}}"],
                capture_output=True,
                text=True,
                check=True
            )
            return container_name in result.stdout

        except subprocess.CalledProcessError:
            return False


# 全局单例
_launcher: Optional[SandboxLauncher] = None


def get_sandbox_launcher() -> SandboxLauncher:
    """获取全局启动器单例"""
    global _launcher
    if _launcher is None:
        _launcher = SandboxLauncher()
    return _launcher
