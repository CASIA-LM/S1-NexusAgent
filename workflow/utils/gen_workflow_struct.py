import json

from dotenv import load_dotenv

from workflow.graph import get_unknown_science_graph
from workflow.utils.unknown_task2flock import format_trace_to_flock

load_dotenv()


def convert_to_json_serializable(data):
    """
    递归地将包含langgraph Node对象的数据结构转换为可JSON序列化的格式。
    """
    if isinstance(data, dict):
        # 如果是字典，递归处理它的值
        return {key: convert_to_json_serializable(value) for key, value in data.items()}
    elif isinstance(data, list):
        # 如果是列表，递归处理它的每个元素
        return [convert_to_json_serializable(item) for item in data]
    elif hasattr(data, '__dict__'):
        return {k: convert_to_json_serializable(v) for k, v in data.__dict__.items()}
    else:
        # 对于其他基本类型，直接返回
        return data


def load_formatted_json(file_path):
    """
    读取整个文件内容，并将其解析为一个 Python 字典
    """
    import os
    print(os.path.abspath(file_path))
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            # 1. 读取整个文件内容为一个字符串
            json_string = f.read()
            restored_data = json.loads(json_string)

            return restored_data
    except FileNotFoundError:
        print(f"错误：文件未找到 at {file_path}")
        return None
    except json.JSONDecodeError as e:
        print(f"JSON 解析错误：文件内容可能不是一个完整的 JSON 对象。错误详情: {e}")
        return None


def load_tool_table(file_path):
    tool_list = load_formatted_json(file_path)
    tool_table = dict()
    for t in tool_list:
        for s in t["scenes"]:
            tool_table[s["scene_name"]] = t["tool_id"]
    return tool_table


async def gen_struct(outline, query):
    # print(len(initial_state))
    # return
    graph = await get_unknown_science_graph()

    tool_table_path = "tool_table.json"
    ToolTable = load_tool_table(tool_table_path)
    trace = []
    final_output = None
    async for output in graph.astream({"messages": query, "outline": outline}, config={"recursion_limit": 200}):
        output = convert_to_json_serializable(output)
        final_output = output
        trace.append(output)
        print(f"output: {output}")
    data = {
        "question": query,
        "trace": trace,
    }
    f = format_trace_to_flock(data, ToolTable)
    return f
