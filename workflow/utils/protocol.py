from typing import Dict, Any, List
import uuid
import json


def build_tools_protocol(
        tool_name: str,
        content_data: Dict[str, Any] = None,
        status: str = "success",
        metadata: Dict[str, Any] = None
) -> Dict[str, Any]:
    """构建嵌套式langgraph协议结构

    Args:
        tool_name: 工具名称(如"求解方程式")
        content_data: 内容数据字典，可以包含code/message/data等
        status: 执行状态(success/failed等)
        metadata: 额外的元数据

    Returns:
        符合嵌套式协议结构的字典
    """

    # 构建外层协议结构
    protocol = {
        "stream_tools": {
            "messages": [
                {
                    "content": json.dumps(content_data),
                    # "additional_kwargs": {},
                    # "response_metadata": metadata or {},
                    "type": "tools",
                    "name": tool_name,
                    # "id": str(uuid.uuid4()),
                    # "tool_call_id": f"chatcmpl-tool-{str(uuid.uuid4())}",
                    # "artifact": None,
                    "status": status
                }
            ]
        }
    }

    return protocol
