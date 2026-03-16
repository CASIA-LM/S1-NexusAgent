"""自动日志保存配置模块。

在 CLI 启动时自动配置日志，将所有输出保存到文件。
"""

import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional


class TeeStream:
    """同时输出到多个流的包装器。"""

    def __init__(self, *streams):
        self.streams = streams

    def write(self, data):
        for stream in self.streams:
            stream.write(data)
            stream.flush()

    def flush(self):
        for stream in self.streams:
            stream.flush()

    def isatty(self):
        return False


def setup_auto_logging(
    log_dir: str | Path = "logs",
    log_level: str = "INFO",
    capture_stdout: bool = True,
    capture_stderr: bool = True,
) -> tuple[Path, Optional[object], Optional[object]]:
    """配置自动日志保存。

    Args:
        log_dir: 日志目录路径
        log_level: 日志级别（DEBUG, INFO, WARNING, ERROR）
        capture_stdout: 是否捕获 stdout 输出
        capture_stderr: 是否捕获 stderr 输出

    Returns:
        3-tuple: (日志文件路径, 原始stdout, 原始stderr)
    """
    # 创建日志目录
    log_dir = Path(log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)

    # 生成带时间戳的日志文件名
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_file = log_dir / f"nexus_cli_{timestamp}.log"

    # 配置 logging 模块
    logging.basicConfig(
        level=getattr(logging, log_level.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[
            logging.FileHandler(log_file, encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
    )

    # 捕获 stdout 和 stderr
    original_stdout = None
    original_stderr = None

    if capture_stdout:
        original_stdout = sys.stdout
        log_file_handle = open(log_file, "a", encoding="utf-8")
        sys.stdout = TeeStream(original_stdout, log_file_handle)

    if capture_stderr:
        original_stderr = sys.stderr
        if not capture_stdout:
            log_file_handle = open(log_file, "a", encoding="utf-8")
        sys.stderr = TeeStream(original_stderr, log_file_handle)

    # 记录启动信息
    logger = logging.getLogger(__name__)
    logger.info("=" * 80)
    logger.info(f"NexusAgent CLI 启动 - 日志文件: {log_file}")
    logger.info(f"日志级别: {log_level}")
    logger.info("=" * 80)

    return log_file, original_stdout, original_stderr


def cleanup_logging(original_stdout, original_stderr):
    """恢复原始的 stdout/stderr。"""
    if original_stdout is not None:
        sys.stdout = original_stdout
    if original_stderr is not None:
        sys.stderr = original_stderr
