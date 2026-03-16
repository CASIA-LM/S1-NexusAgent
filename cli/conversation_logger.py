"""对话历史记录器。

自动保存用户输入和 Agent 输出的完整对话内容。
"""

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Optional


class ConversationLogger:
    """对话历史记录器。"""

    def __init__(
        self,
        log_dir: str | Path = "logs/conversations",
        thread_id: Optional[str] = None,
        format: str = "both",  # "txt", "json", or "both"
    ):
        """初始化对话记录器。

        Args:
            log_dir: 对话日志目录
            thread_id: 会话 ID
            format: 日志格式 ("txt", "json", or "both")
        """
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)

        self.thread_id = thread_id or "unknown"
        self.format = format

        # 生成日志文件名
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_thread_id = self.thread_id[:8] if len(self.thread_id) > 8 else self.thread_id

        self.txt_file = self.log_dir / f"conversation_{timestamp}_{safe_thread_id}.txt"
        self.json_file = self.log_dir / f"conversation_{timestamp}_{safe_thread_id}.json"

        self.conversation_data = {
            "thread_id": self.thread_id,
            "start_time": datetime.now().isoformat(),
            "messages": [],
        }

        # 初始化文本日志文件
        if self.format in ("txt", "both"):
            self._init_txt_log()

    def _init_txt_log(self):
        """初始化文本日志文件。"""
        with open(self.txt_file, "w", encoding="utf-8") as f:
            f.write("=" * 80 + "\n")
            f.write(f"NexusAgent 对话记录\n")
            f.write(f"会话 ID: {self.thread_id}\n")
            f.write(f"开始时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write("=" * 80 + "\n\n")

    def log_user_message(self, content: str):
        """记录用户消息。

        Args:
            content: 用户输入内容
        """
        timestamp = datetime.now().isoformat()
        message_data = {
            "role": "user",
            "content": content,
            "timestamp": timestamp,
        }
        self.conversation_data["messages"].append(message_data)

        # 写入文本日志
        if self.format in ("txt", "both"):
            with open(self.txt_file, "a", encoding="utf-8") as f:
                f.write(f"[{datetime.now().strftime('%H:%M:%S')}] 用户:\n")
                f.write(f"{content}\n\n")

        # 更新 JSON 日志
        if self.format in ("json", "both"):
            self._save_json()

    def log_assistant_message(self, content: str, metadata: Optional[dict] = None):
        """记录 Agent 回复。

        Args:
            content: Agent 回复内容
            metadata: 额外的元数据（如节点名称、工具调用等）
        """
        timestamp = datetime.now().isoformat()
        message_data = {
            "role": "assistant",
            "content": content,
            "timestamp": timestamp,
        }
        if metadata:
            message_data["metadata"] = metadata

        self.conversation_data["messages"].append(message_data)

        # 写入文本日志
        if self.format in ("txt", "both"):
            with open(self.txt_file, "a", encoding="utf-8") as f:
                f.write(f"[{datetime.now().strftime('%H:%M:%S')}] Agent:\n")
                f.write(f"{content}\n")
                if metadata:
                    f.write(f"  [元数据: {metadata}]\n")
                f.write("\n")

        # 更新 JSON 日志
        if self.format in ("json", "both"):
            self._save_json()

    def log_system_message(self, content: str, event_type: Optional[str] = None):
        """记录系统消息（如进度、工具调用等）。

        Args:
            content: 系统消息内容
            event_type: 事件类型（如 "progress", "tool_call", "error"）
        """
        timestamp = datetime.now().isoformat()
        message_data = {
            "role": "system",
            "content": content,
            "timestamp": timestamp,
        }
        if event_type:
            message_data["event_type"] = event_type

        self.conversation_data["messages"].append(message_data)

        # 写入文本日志
        if self.format in ("txt", "both"):
            with open(self.txt_file, "a", encoding="utf-8") as f:
                f.write(f"[{datetime.now().strftime('%H:%M:%S')}] 系统")
                if event_type:
                    f.write(f" [{event_type}]")
                f.write(f": {content}\n")

        # 更新 JSON 日志
        if self.format in ("json", "both"):
            self._save_json()

    def log_node_event(self, node: str, event_type: str, content: str, **kwargs):
        """记录节点事件。

        Args:
            node: 节点名称
            event_type: 事件类型
            content: 事件内容
            **kwargs: 额外的事件数据
        """
        timestamp = datetime.now().isoformat()
        message_data = {
            "role": "node_event",
            "node": node,
            "event_type": event_type,
            "content": content,
            "timestamp": timestamp,
        }
        message_data.update(kwargs)

        self.conversation_data["messages"].append(message_data)

        # 写入文本日志
        if self.format in ("txt", "both"):
            with open(self.txt_file, "a", encoding="utf-8") as f:
                # 对于 execute_content，使用特殊格式（多行缩进）
                if event_type == "execute_content":
                    f.write(f"[{datetime.now().strftime('%H:%M:%S')}] [{node}] 执行内容:\n")
                    # 将内容按行缩进
                    for line in content.split('\n'):
                        f.write(f"    {line}\n")
                    f.write("\n")
                else:
                    f.write(f"[{datetime.now().strftime('%H:%M:%S')}] [{node}] {event_type}: {content}\n")

        # 更新 JSON 日志
        if self.format in ("json", "both"):
            self._save_json()

    def _save_json(self):
        """保存 JSON 格式的对话历史。"""
        self.conversation_data["last_updated"] = datetime.now().isoformat()
        with open(self.json_file, "w", encoding="utf-8") as f:
            json.dump(self.conversation_data, f, ensure_ascii=False, indent=2)

    def finalize(self):
        """完成对话记录，写入结束信息。"""
        self.conversation_data["end_time"] = datetime.now().isoformat()

        # 写入文本日志结束标记
        if self.format in ("txt", "both"):
            with open(self.txt_file, "a", encoding="utf-8") as f:
                f.write("\n" + "=" * 80 + "\n")
                f.write(f"对话结束时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
                f.write(f"总消息数: {len(self.conversation_data['messages'])}\n")
                f.write("=" * 80 + "\n")

        # 保存最终的 JSON
        if self.format in ("json", "both"):
            self._save_json()

    def get_log_files(self) -> dict[str, Path]:
        """获取日志文件路径。

        Returns:
            包含 txt_file 和 json_file 的字典
        """
        return {
            "txt_file": self.txt_file if self.format in ("txt", "both") else None,
            "json_file": self.json_file if self.format in ("json", "both") else None,
        }
