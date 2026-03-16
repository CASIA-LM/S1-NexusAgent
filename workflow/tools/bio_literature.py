from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
from langchain_core.tools import StructuredTool
import gget  # 假设 gget 已正确安装
import gseapy
from pydantic import BaseModel, Field
from typing import Optional, Dict, Any
from langchain_core.prompts import PromptTemplate
from difflib import get_close_matches
import httpx
from bs4 import BeautifulSoup
from langchain_openai import ChatOpenAI
import json
from workflow.const import Tools
from workflow.utils.minio_utils import upload_content_to_minio
from urllib.parse import urljoin
import json


from dotenv import load_dotenv
import httpx
import json

from workflow import config as science_config
from playwright.async_api import async_playwright
from typing import List, Optional, Dict, Any
from typing import cast
from openai import APITimeoutError, OpenAI, Timeout
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import InjectedToolArg
from pydantic import BaseModel, Field
from typing_extensions import Annotated
from urllib.parse import urlparse
from typing import Dict, Any
from langchain_core.tools import tool
from langchain_openai import ChatOpenAI
from crawl4ai import (
    AsyncWebCrawler,
    CrawlerRunConfig,
    DefaultMarkdownGenerator,
    PruningContentFilter,
)


def call_llm(messages, provider, model_name):

    default_model_names = {
        # "DeepSeek": "deepseek-v3.1",
        "DeepSeek": "DeepSeekV3",
        "OpenAI": "gpt-4.1",  # gpt-4o-free
        "Qwen": "qwen3",
        "Google": "gemini-2.5-pro",
    }

    client = OpenAI(
        base_url=science_config.DeepSeekV3.base_url,
        api_key=science_config.DeepSeekV3.api_key,
        timeout=Timeout(connect=10, read=60, write=10, pool=3),
    )
    try:
        response = client.chat.completions.create(
            model=model_name or default_model_names[provider],
            messages=messages,
            # stream=True,
            temperature=0.2,
        )
        return response
    except APITimeoutError as e:
        raise e
# === 工具 1: 网页爬取 ===
# 测试成功
# query：把 https://www.wikipedia.org/ 这个网址的主要文本内容提取出来。
class ExtractUrlContentInput(BaseModel):
    url: str = Field(..., description="网页 URL")

async def extract_url_content_coroutine(url: str) -> Dict[str, Any]:
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(url, headers={"User-Agent": "Mozilla/5.0"})
            response.raise_for_status()

        content_type = response.headers.get("Content-Type", "")

        # 纯文本或JSON直接返回文本
        if "text/plain" in content_type or "application/json" in content_type:
            return {"success": True, "content": response.text.strip()}

        # HTML内容解析
        soup = BeautifulSoup(response.text, "html.parser")
        content = soup.find("main") or soup.find("article") or soup.body
        if not content:
            return {"success": False, "error": "无法定位网页主体内容"}

        # 移除不需要的标签
        for element in content(["script", "style", "nav", "header", "footer", "aside", "iframe"]):
            element.decompose()

        paragraphs = content.find_all(["p", "h1", "h2", "h3", "h4", "h5", "h6"])
        cleaned_text = [p.get_text().strip() for p in paragraphs if p.get_text().strip()]

        api_result = "\n\n".join(cleaned_text)

        # ========================
        # 你指定的截断方式在此处理
        # ========================
        if isinstance(api_result, dict):
            text = json.dumps(api_result, ensure_ascii=False)
        else:
            text = str(api_result)

        result = text  # 默认值
        if len(text) > 10000:
            result = (
                "The output is too long to be added to context. "
                "Here are the first 10K characters...\n\n" + text[:10000]
            )

        return {"success": True, "content": result}

    except Exception as e:
        return {"success": False, "error": f"网页内容提取失败: {str(e)}"}

extract_url_content_tool = StructuredTool.from_function(
    coroutine=extract_url_content_coroutine,
    name=Tools.extract_url_content,
    description="""
    【领域：生物】Extract the text content of a webpage using requests and BeautifulSoup.

    Args:
        url: Webpage URL to extract content from

    Returns:
        Text content of the webpage

    """,
    args_schema=ExtractUrlContentInput,
    metadata={"args_schema_json":ExtractUrlContentInput.schema()} 
)



async def fetch_dynamic_html(url: str) -> str:
    async with async_playwright() as p:
        print(f"Fetching dynamic HTML content from: {url}")
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        response = await page.goto(url, wait_until="networkidle")
        content = await page.content()
        await browser.close()
        
        if response and response.status != 200:
            raise Exception(f"HTTP error {response.status} when fetching {url}")

        return content

# 网页爬取工具
class WebCrawlInput(BaseModel):
    url: str = Field(
        ..., description="The URL to scrape, e.g., https%3A%2F%2Fbaike.baidu.com%2F"
    )
    query: Optional[str] = Field(
        default=None,
        description="[Optional]: The term you want to focus on. Do not pass this parameter if you just want to directly return the whole content of the webpage.",
    )

class WebCrawlOutput(BaseModel):
    content: str = Field(
        ..., description="The abstracted webpage content based on the query."
    )

async def web_crawl(
    url: str,
    query: Optional[str] = None,
    *,
    config: Annotated[RunnableConfig, InjectedToolArg],
) -> Dict[str, Any]:
    content_filter = PruningContentFilter(
        user_query=query, threshold=0.1, threshold_type="fixed"
    )
    md_generator = DefaultMarkdownGenerator(
        content_filter=content_filter,
        options={"ignore_links": True, "ignore_images": False, "escape_html": False, "body_width": 80},
    )
    config = CrawlerRunConfig(
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36",
        markdown_generator=md_generator,
    )

    try:
        dynamic_html = await fetch_dynamic_html(url)
        print(f"Finish fetching.")
        markdown_result = md_generator.generate_markdown(input_html=dynamic_html)
        if not markdown_result.raw_markdown.strip():
            raise Exception("Crawled content is empty.")
        with open("debug_web_crawl_output.md", "w", encoding="utf-8") as f:
            f.write(markdown_result.raw_markdown)
        if not query:
            return {"content": markdown_result.raw_markdown}
        messages = [
            {
                "role": "system",
                "content": [
                    {
                        "type": "text",
                        "text": "You are a webpage content summarization assistant.",
                    }
                ],
            },
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": (
                            f"Here is the webpage content:\n{markdown_result.fit_markdown}\n\nPlease extract the relevant information about the following question: {query}."
                            "If there are tables, sections, or paragraphs in the original content that are directly related to the question, please provide the original text (including tables, headings, and paragraphs) as-is. "
                        ),
                    }
                ],
            },
        ]
        response_llm = call_llm(messages, "DeepSeek", None)
        summary = response_llm.choices[0].message.content
        return {"content": summary}
    except Exception as e:
        try:
            print(f"Web crawl with playwright failed: {str(e)}. Trying jina read as fallback.")
            # 尝试使用jina read作为后备方案
            #scrape_result = await jina_read(url, config=None)
            scrape_result = ''
            return scrape_result
        except Exception as scrape_error:
            return {"error": f"Web crawl failed: {str(scrape_error)}. The URL may not be accessible."}

web_crawl_tool = StructuredTool.from_function(
    coroutine=web_crawl,
    name="webpage_content_crawler",
    description="Using web crawl tool to crawl webpage content, with a query to focus on specific information. Prioritize using this tool for getting markdown content of a webpage. Doesn't include non-html content, e.g. arxiv pdf links.",
    args_schema=WebCrawlInput,
    metadata={
        "args_schema_json": WebCrawlInput.model_json_schema(),
        "output_schema_json": WebCrawlOutput.model_json_schema(),
    },
)

# === 工具 2: PubMed 文献查询工具 ===
# query1:能否检索包含 circRNA 与 cancer 的综述类文献。
# query2:CRISPR基因编辑在人类胰腺癌中的应用
# 测试成功
class QueryPubMedInput(BaseModel):
    """
    PubMed 文献检索工具输入参数模型
    """
    query: str = Field(..., description="检索关键词或查询字符串，例如: 'CRISPR gene editing'")
    max_papers: int = Field(3, description="最多检索论文数量，默认 3 篇，不可改变该参数")
    max_retries: int = Field(3, description="最大重试次数，当初次查询无结果时简化查询重试，默认 3 次")

def query_pubmed_coroutine(
    query: str,
    max_papers: int = 3,
    max_retries: int = 3
) -> Dict[str, Any]:
    """
    基于检索关键词从 PubMed 获取文献列表：
      1. 首次尝试获取最多 max_papers 篇文献
      2. 若无结果，最多简化查询重试 max_retries 次

    返回示例:
    {
      "papers": [
        {"title": "...", "abstract": "...", "journal": "..."},
        ...
      ],
      "message": "检索成功" 或 错误信息
    }
    """
    from pymed import PubMed
    import time

    try:
        pubmed = PubMed(tool="LangGraphAgent", email="your-email@example.com")
        results = []
        papers = list(pubmed.query(query, max_results=max_papers))
        retries = 0
        while not papers and retries < max_retries:
            retries += 1
            simplified = ' '.join(query.split()[:-retries]) or query
            time.sleep(1)
            papers = list(pubmed.query(simplified, max_results=max_papers))
        if not papers:
            return {"papers": [], "message": "未检索到相关文献"}
        for paper in papers:
            results.append({
                "title": paper.title,
                "abstract": paper.abstract,
                "journal": paper.journal
            })
        return {"papers": results, "message": "检索成功，共获取 {} 篇文献".format(len(results))}
    except Exception as e:
        return {"error": f"PubMed 检索出错: {str(e)}"}

#创建 QueryPubMed 工具
query_pubmed_tool = StructuredTool.from_function(
    function=query_pubmed_coroutine,
    func=query_pubmed_coroutine,
    name=Tools.QUERY_PUBMED,
    description="""
    【领域：生物】
    从 PubMed 检索文献列表。
    返回字段：
      - papers: 文献列表，每条包含 title, abstract, journal
      - message: 检索状态或错误信息
    """,
    args_schema=QueryPubMedInput,
    metadata={"args_schema_json":QueryPubMedInput.schema()}
)


# === 工具 4: 搜索arxiv论文 ===
# 测试成功：请你帮我搜关于agent进化的论文
class ArxivQueryInput(BaseModel):
    query: str = Field(..., description="The search query string for arXiv")
    max_papers: Optional[int] = Field(5, description="Maximum number of papers to retrieve")

async def query_arxiv(
    query: str,
    max_papers: Optional[int] = 5
) -> Dict[str, Any]:
    import arxiv
    log = f"# arXiv Query Log\nQuery: {query}\nMax papers: {max_papers}\n"

    try:
        client = arxiv.Client()
        search = arxiv.Search(
            query=query,
            max_results=max_papers,
            sort_by=arxiv.SortCriterion.Relevance
        )
        papers = list(client.results(search))
        if not papers:
            log += "No papers found on arXiv.\n"
            return {"research_log": log, "results_text": ""}
        
        results_text = ""
        for paper in papers:
            results_text += f"Title: {paper.title}\nSummary: {paper.summary}\n\n"
        log += f"Retrieved {len(papers)} papers from arXiv.\n"
        return {"research_log": log, "results_text": results_text.strip()}
    except Exception as e:
        log += f"Error querying arXiv: {e}\n"
        return {"research_log": log, "results_text": ""}

query_arxiv_tool = StructuredTool.from_function(
    name=Tools.query_arxiv,
    coroutine=query_arxiv,
    description="""
    【领域：生物】
        "根据搜索关键词查询 arXiv 论文，并返回标题与摘要。\n\n"
        "返回：\n"
        " - research_log: 查询过程和结果日志\n"
        " - results_text: 查询到的论文标题和摘要文本"
    """,
    args_schema=ArxivQueryInput,
    metadata={"args_schema_json": ArxivQueryInput.schema()}
)



# === 工具 5: 搜索google scholar论文 ===
# 测试成功：请你帮我搜关于agent进化的论文
class ScholarQueryInput(BaseModel):
    query: str = Field(..., description="The search query string for Google Scholar")

async def query_scholar_coroutine(
    query: str
) -> Dict[str, Any]:
    from scholarly import scholarly
    log = f"# Google Scholar Query Log\nQuery: {query}\n"

    try:
        search_query = scholarly.search_pubs(query)
        result = next(search_query, None)
        if result:
            results_text = (
                f"Title: {result['bib'].get('title', '')}\n"
                f"Year: {result['bib'].get('pub_year', '')}\n"
                f"Venue: {result['bib'].get('venue', '')}\n"
                f"Abstract: {result['bib'].get('abstract', '')}"
            )
            log += "Successfully retrieved first search result from Google Scholar.\n"
            return {"research_log": log, "results_text": results_text}
        else:
            log += "No results found on Google Scholar.\n"
            return {"research_log": log, "results_text": ""}
    except Exception as e:
        log += f"Error querying Google Scholar: {e}\n"
        return {"research_log": log, "results_text": ""}

query_scholar_tool = StructuredTool.from_function(
    name=Tools.query_scholar,
    description="""
    【领域：生物】
        "根据搜索关键词查询 Google Scholar 论文，并返回第一条搜索结果的标题、年份、期刊/会议和摘要。\n\n"
        "返回：\n"
        " - research_log: 查询过程和结果日志\n"
        " - results_text: 查询到的论文信息文本"
    """,
    args_schema=ScholarQueryInput,
    coroutine=query_scholar_coroutine,
    metadata={"args_schema_json": ScholarQueryInput.schema()}
)


