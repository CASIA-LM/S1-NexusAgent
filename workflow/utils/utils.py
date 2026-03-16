"""Utility & helper functions."""
import json
from datetime import timedelta
from typing import Any, Dict, List, Optional, Tuple
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.client.sse import sse_client
from langchain.chat_models import init_chat_model
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import BaseMessage

from PIL import Image
import asyncio
from playwright.async_api import async_playwright
from langchain_core import documents
from langchain_community.document_loaders import JSONLoader, BSHTMLLoader, Docx2txtLoader, CSVLoader

from workflow.state import WorkflowTeamState

def get_message_text(msg: BaseMessage) -> str:
    """Get the text content of a message."""
    content = msg.content
    if isinstance(content, str):
        return content
    elif isinstance(content, dict):
        return content.get("text", "")
    else:
        txts = [c if isinstance(c, str) else (c.get("text") or "") for c in content]
        return "".join(txts).strip()


def load_chat_model(fully_specified_name: str) -> BaseChatModel:
    """Load a chat model from a fully specified name.

    Args:
        fully_specified_name (str): String in the format 'provider/model'.
    """
    provider, model = fully_specified_name.split("/", maxsplit=1)
    return init_chat_model(model, model_provider=provider, temperature=0)


def filter_think(ai_content):
    start_index = ai_content.find('</think>')
    if start_index != -1:
        result = ai_content[start_index + len('</think>'):].strip()
    else:
        result = ai_content

    return result


def split_query_config(content) -> Tuple[str, Dict]:
    config = {}
    try:
        full = json.loads(content) or {}
        return full.get('query'), full.get('config')

    except json.decoder.JSONDecodeError as e:
        return content, config


async def _get_tools_from_client_session(
        client_context_manager: Any, timeout_seconds: int = 10
) -> List:
    """
    Helper function to get tools from a client session.

    Args:
        client_context_manager: A context manager that returns (read, write) functions
        timeout_seconds: Timeout in seconds for the read operation

    Returns:
        List of available tools from the MCP server

    Raises:
        Exception: If there's an error during the process
    """
    async with client_context_manager as (read, write):
        async with ClientSession(
                read, write, read_timeout_seconds=timedelta(seconds=timeout_seconds)
        ) as session:
            # Initialize the connection
            await session.initialize()
            # List available tools
            listed_tools = await session.list_tools()
            return listed_tools.tools


async def load_mcp_tools(
        server_type: str,
        command: Optional[str] = None,
        args: Optional[List[str]] = None,
        url: Optional[str] = None,
        env: Optional[Dict[str, str]] = None,
        timeout_seconds: int = 3,  # Longer default timeout for first-time executions
):
    """
    Load tools from an MCP server.

    Args:
        server_type: The type of MCP server connection (stdio or sse)
        command: The command to execute (for stdio type)
        args: Command arguments (for stdio type)
        url: The URL of the SSE server (for sse type)
        env: Environment variables
        timeout_seconds: Timeout in seconds (default: 60 for first-time executions)

    Returns:
        Bool
        List of available tools from the MCP server

    """
    try:
        if server_type == "stdio":
            if not command:
                return False, None

            server_params = StdioServerParameters(
                command=command,
                args=args,  # Optional command line arguments
                env=env,  # Optional environment variables
            )

            return await _get_tools_from_client_session(
                stdio_client(server_params), timeout_seconds
            )

        elif server_type == "sse":
            if not url:
                return False, None

            return await _get_tools_from_client_session(
                sse_client(url=url), timeout_seconds
            )

        else:
            return False, None

    except Exception as e:
        print(e)
        _ = e
        return False, None


def get_scene_desc_from_desc(description) -> Tuple[str, str]:
    try:
        content = json.loads(description)
        return content.get('scene'), content.get('description')

    except json.decoder.JSONDecodeError as e:
        return description, description




if __name__ == '__main__':
    # a = "[\"women\"]"
    a = {
        "query": "可以帮忙进行蛋白质序列预测吗",
        "config": {
            "uid": 6
        }
    }
    import json

    b = json.dumps(a)
    print(b)



# def pdf_to_images_base64(pdf_path: str) -> List[str]:
#     """
#     将PDF文件的所有页面转换为Base64编码的PNG图片列表。

#     参数:
#         pdf_path (str): 输入的PDF文件路径。

#     返回:
#         List[str]: 包含每个页面Base64编码字符串的列表。
#     """
#     try:
#         pdf_document = fitz.open(pdf_path)
#     except Exception as e:
#         print(f"错误：无法打开PDF文件 '{pdf_path}'. {e}")
#         return []

#     base64_images = []
#     # 遍历PDF的每一页
#     for page_num in range(len(pdf_document)):
#         page = pdf_document.load_page(page_num)
        
#         # 将页面渲染为像素图 (pixmap)
#         # 你可以增加 zoom 因子来提高分辨率, 例如 pix = page.get_pixmap(matrix=fitz.Matrix(2, 2))
#         pix = page.get_pixmap()
        
#         # 从像素数据创建PIL图像
#         if pix.alpha:
#             # 处理带alpha通道的PNG
#             img = Image.frombytes("RGBA", [pix.width, pix.height], pix.samples)
#         else:
#             # 处理不带alpha通道的RGB
#             img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)

#         # 将图像存入内存缓冲区
#         buffer = io.BytesIO()
#         img.save(buffer, format="PNG")
        
#         # 获取缓冲区的字节值并进行Base64编码
#         img_base64 = base64.b64encode(buffer.getvalue()).decode("utf-8")
#         base64_images.append(img_base64)
    
#     pdf_document.close()
#     return base64_images


# def excel_to_image(excel_file: str, image_file: str):
#     """
#     将 Excel 文件的工作表转换为图片。

#     :param excel_file: 输入的 Excel 文件路径 (.xlsx)
#     :param image_file: 输出的图片文件路径 (.png)
#     """
#     try:
#         # 直接读取Excel文件
#         df = pd.read_excel(excel_file)  

#         # 将 DataFrame 导出为图片
#         dfi.export(df, image_file)
    
#         print(f"成功将 {excel_file} 转换为 {image_file}")

#     except FileNotFoundError:
#         print(f"错误：文件 {excel_file} 未找到。")
#     except Exception as e:
#         print(f"发生错误：{e}")

# def csv_to_image(csv_file: str, image_file: str):
#     df = pd.read_csv(csv_file)
#     dfi.export(df, image_file)
#     print(f"成功将 {csv_file} 转换为 {image_file}")
#     return image_file

# def csv_to_text(csv_file: str):
#     loader = CSVLoader(csv_file)
#     documents = loader.load()
#     page_contents = []
#     for document in documents:
#         page_contents.append(document.page_content)
#     return "\n---\n".join(page_contents)

# def json_to_text(json_file: str):
    
    
#     loader = JSONLoader(
#     file_path=json_file,
#     jq_schema='.', # Use '.' to load the entire JSON object
#     text_content=False # Set to False to get the structured data
#     )

#     documents = loader.load()
#     loaded_data = documents[0].page_content
#     return loaded_data

# def html_to_text(html_file: str):
#     loader = BSHTMLLoader(html_file)
#     documents = loader.load()
#     loaded_data = documents[0].page_content
#     return loaded_data

# def zip_to_data(zip_file: str):
#     with zipfile.ZipFile(zip_file, 'r') as zip_ref:
#         zip_ref.extractall("./zip_docs")

#     documents = []
#     for filename in os.listdir("./zip_docs"):
#         file_path = os.path.join("./zip_docs", filename)

    
#         if filename.endswith(".pdf"):
#             images = pdf_to_images_base64(file_path)
#             for image in images:
#                 documents.append({"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": image}})
#         elif filename.endswith(".xls") or filename.endswith(".xlsx"):
#             excel_to_image(file_path, "D:\\documents\\projects\\dev-api-langgraph-5.0\\dev-api-langgraph\\tmp_data\\excel_image.png")
#             base64_image = encode_image("D:\\documents\\projects\\dev-api-langgraph-5.0\\dev-api-langgraph\\tmp_data\\excel_image.png")
#             documents.append({"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": base64_image}})
#         elif filename.endswith(".json"):
#             document = json_to_text(file_path)
#             documents.append({"type": "json", "text": document})
#         elif filename.endswith(".html"):
#             document = html_to_text(file_path)
#             documents.append({"type": "text", "text": document})
#         elif filename.endswith(".pptx"):
#             pptx_dicts = pptx_to_dicts(file_path)
#             documents.append({"type": "text", "text": "\n---\n".join([f"Page {slide['page_number']}\n{slide['page_content']}" for slide in pptx_dicts])})
#         elif filename.endswith(".mp3"):
#             document = audio_to_text(file_path)
#             documents.append({"type": "text", "text": document})

#     return documents

# def pptx_to_dicts(file_path: str) -> list:
#     '''
#     Convert pptx file to a list of dicts,
#     the format of each dict(slide) is:
#     {
#         "page_number": int,
#         "page_content": str,
#     }
#     '''
#     prs = Presentation(file_path)
#     slides = []
#     for i, slide in enumerate(prs.slides):
#         text = []
#         for shape in slide.shapes:
#             if hasattr(shape, "text"):
#                 text.append(shape.text)
#         slides.append({
#             "page_number": i+1,
#             "page_content": "\n".join(text)
#         })
#     return slides



# def docx_to_text(file_path: str):
#     loader = Docx2txtLoader(file_path)
#     loaded_data = loader.load()
#     return loaded_data[0].page_content



# def load_text_file(file_path: str) -> str:
#     """Loads content from a specified text file."""
#     try:
#         with open(file_path, "r", encoding="utf-8") as f:
#             content = f.read()
#         return content
#     except FileNotFoundError:
#         return f"Error: File not found at {file_path}"
#     except Exception as e:
#         return f"An error occurred: {e}"


# def encode_image(image_path):
#     with open(image_path, "rb") as image_file:
#         return base64.b64encode(image_file.read()).decode("utf-8")


# def count_csv_lines(file_path: str):
#     """
#     通过逐行迭代快速计算CSV文件的行数（不含表头）。
#     """
#     with open(file_path, 'r', encoding='utf-8') as f:
#         # 跳过表头
#         next(f, None)
#         # 迭代文件的剩余部分并计数
#         return sum(1 for row in csv.reader(f))


# def is_valid_feedback(feedback: str) -> bool:
#     """
#     Check if the feedback is valid.
#     """
#     if not isinstance(feedback, str):
#         print("不是字符串")
#         return False
#     try:
#         json.loads(feedback)
#         print("正在判断")
#         return True
#     except json.JSONDecodeError:
#         return False
    

def message_to_str_detailed(messages):
    index = 0
    part = ""
    # 需要带索引的遍历：
    for msg in messages:
        if (isinstance(msg, ToolMessage) or (isinstance(msg, AIMessage))):
            index += 1
            """将单个消息转换为详细的字符串格式"""
            if hasattr(msg, 'content'):
                part += f"步骤{index}执行结果摘要: \n{msg.content}\n"        
            
    return part


def format_reviews_with_numbering(reviews) -> str:
    if not reviews or len(reviews) == 0:
        return "没有执行记录。"
    
    lines = []
    for i, review in enumerate(reviews):
        if review.completion_status == "completed":
            status = "成功"
        else:
            status = "失败"
        lines.append(f"\n步骤{i + 1}: ")
        lines.append(f"  执行状态: {status}")
        lines.append(f"  执行结果总结: {review.abstract}")
    
    return "\n".join(lines)

# 0909
# def build_checklist(state: WorkflowTeamState, history_sum) -> dict:
#     checklist = []
#     plan_nodes = state.get("cur_plan", [])
#     current_position = state.get("current_position",0)

#     for i, plan_node in enumerate(plan_nodes):
#         if i < current_position:
#             if history_sum[i].invoke_status == "success":
#                 status = "[✓]"
#             else:
#                 status = "[✗]"
#         elif i == current_position:
#             status = "[>]"
#         else :
#             status = "[ ]"
#         checklist.append(f"{i+1}. {status} {plan_node.content.strip()}")

#     plan_str = "\n".join(checklist)

#     return plan_str

# checklist改成了json形式
def build_checklist(state: WorkflowTeamState, history_sum) -> dict:
    """
    [重构后]
    根据工作流的当前状态，构建一个描述计划执行情况的字典 (JSON对象)。
    Args:
        state (WorkflowTeamState): 工作流的当前状态。
        history_sum: 已执行步骤的历史摘要列表。

    Returns:
        dict: 一个包含当前计划和所有计划状态列表的字典。
    """
    plans_list = []
    plan_nodes = state.get("planner_steps")
    current_position = state.get("current_position", 0)
    current_plan_str = ""

    for i, plan_node in enumerate(plan_nodes):
        plan_content = plan_node.content.strip()
        status = ""

        if i < current_position:
            # 已执行的步骤
            # 假设 history_sum[i] 存在且具有 'invoke_status' 属性
            if history_sum and i < len(history_sum) and hasattr(history_sum[i], 'invoke_status'):
                if history_sum[i].invoke_status == "success":
                    status = "success"  # 对应之前的 "[✓]"
                else:
                    status = "failed"     # 对应之前的 "[✗]"
            else:
                # 如果历史记录不完整或状态未知，则标记为失败
                status = "failed"
        elif i == current_position:
            # 正在执行的步骤
            status = "running"        # 对应之前的 "[>]"
            current_plan_str = plan_content
        else:
            # 待执行的步骤
            status = "pending"        # 对应之前的 "[ ]"
        
        plans_list.append({
            "status": status,
            "name": plan_content
        })

    # 构造最终的JSON格式输出
    final_json_output = {
        "current_plan": current_plan_str,
        "plans": plans_list
    }

    return final_json_output

def simple_estimate_tokens(text):
    """
    简单的token量估计，基于经验规则
    - 英文：大约4个字符 = 1个token
    - 中文：大约1.5-2个字符 = 1个token
    """
    if not text:
        return 0
    
    # 统计中英文字符
    chinese_chars = sum(1 for char in text if '\u4e00' <= char <= '\u9fff')
    english_chars = len([char for char in text if char.isalpha() and ord(char) < 128])
    other_chars = len(text) - chinese_chars - english_chars
    
    # 估算token数
    chinese_tokens = chinese_chars / 1.5
    english_tokens = english_chars / 4
    other_tokens = other_chars / 3
    
    return int(chinese_tokens + english_tokens + other_tokens)