import uuid

import json
import logging
import random
from typing import Any
from typing import List, Dict, Optional, Literal

import aiohttp

from aiohttp import FormData
from Bio.Data.IUPACData import protein_letters_3to1  # 从Biopython获取氨基酸代码映射
from bs4 import BeautifulSoup

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field, conint
from pydantic import validator
from workflow import config as science_config
from workflow.const import Tools
from workflow.utils.minio_utils import upload_content_to_minio
from datetime import datetime, timedelta


import os, json, pickle, pandas as pd, numpy as np
from sklearn.metrics.pairwise import cosine_similarity
from langchain_openai import ChatOpenAI
from tqdm.auto import tqdm
from typing import List, Dict, Union, Set, Optional, Any
import requests
#from anthropic import Anthropic
import traceback
import time


DEEPSEEK_CHAT = ChatOpenAI(
        model=science_config.DeepSeekV3.model,
        base_url=science_config.DeepSeekV3.base_url,
        api_key=science_config.DeepSeekV3.api_key,
        temperature=0.3,
        max_tokens=8092
    )

def _query_claude_for_api(prompt, schema, system_template):
    """
    Adapted to use DeepSeekV3 instead of Claude
    """
    try:
        # Format system prompt
        if schema is not None:
            schema_json = json.dumps(schema, indent=2)
            system_prompt = system_template.format(schema=schema_json)
        else:
            system_prompt = system_template

        # 构建完整 prompt：system + user 输入
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt}
        ]

        # 使用 DeepSeekV3 接口执行
        response = DEEPSEEK_CHAT.invoke(messages)

        # 尝试提取 JSON 片段
        if isinstance(response.content, str):
            response_text = response.content.strip()
        else:
            response_text = str(response).strip()

        json_start = response_text.find('{')
        json_end = response_text.rfind('}') + 1

        if json_start >= 0 and json_end > json_start:
            json_text = response_text[json_start:json_end]
            result = json.loads(json_text)
        else:
            result = json.loads(response_text)

        return {
            "success": True,
            "data": result,
            "raw_response": response_text
        }

    except (json.JSONDecodeError, KeyError, IndexError) as e:
        return {
            "success": False,
            "error": f"Failed to parse response: {str(e)}",
            "raw_response": response_text if 'response_text' in locals() else "No content found"
        }
    except Exception as e:
        return {
            "success": False,
            "error": f"Error querying DeepSeek: {str(e)}"
        }
    
def _query_rest_api(endpoint, method="GET", params=None, headers=None, json_data=None, description=None):
    """
    General helper function to query REST APIs with consistent error handling.
    
    Parameters:
    endpoint (str): Full URL endpoint to query
    method (str): HTTP method ("GET" or "POST")
    params (dict, optional): Query parameters to include in the URL
    headers (dict, optional): HTTP headers for the request
    json_data (dict, optional): JSON data for POST requests
    description (str, optional): Description of this query for error messages
    
    Returns:
    dict: Dictionary containing the result or error information
    """
    # Set default headers if not provided
    if headers is None:
        headers = {"Accept": "application/json"}
    
    # Set default description if not provided
    if description is None:
        description = f"{method} request to {endpoint}"

    url_error = None
        
    try:
        # Make the API request
        if method.upper() == "GET":
            response = requests.get(endpoint, params=params, headers=headers)
        elif method.upper() == "POST":
            response = requests.post(endpoint, params=params, headers=headers, json=json_data)
        else:
            return {"error": f"Unsupported HTTP method: {method}"}
        
        url_error = str(response.text)
        response.raise_for_status()
        
        # Try to parse JSON response
        try:
            result = response.json()
        except ValueError:
            # Return raw text if not JSON
            result = {"raw_text": response.text}
        
        return {
            "success": True,
            "query_info": {
                "endpoint": endpoint,
                "method": method,
                "description": description
            },
            "result": result
        }
        
    except requests.exceptions.RequestException as e:
        error_msg = str(e)
        response_text = ""
        
        # Try to get more detailed error info from response
        if hasattr(e, 'response') and e.response:
            try:
                error_json = e.response.json()
                if 'messages' in error_json:
                    error_msg = "; ".join(error_json['messages'])
                elif 'message' in error_json:
                    error_msg = error_json['message']
                elif 'error' in error_json:
                    error_msg = error_json['error']
                elif 'detail' in error_json:
                    error_msg = error_json['detail']
            except:
                response_text = e.response.text
        
        return {
            "success": False,
            "error": f"API error: {error_msg}",
            "query_info": {
                "endpoint": endpoint,
                "method": method,
                "description": description
            },
            "response_url_error": url_error,
            "response_text": response_text
        }
    except Exception as e:
        return {
            "success": False,
            "error": f"Error: {str(e)}",
            "query_info": {
                "endpoint": endpoint,
                "method": method,
                "description": description
            }
        }
    

    
def _query_ncbi_database(
    database: str,
    search_term: str,
    result_formatter = None,
    max_results: int = 3,
) -> Dict[str, Any]:
    """
    Core function to query NCBI databases using Claude for query interpretation and NCBI eutils.
    
    Parameters:
    database (str): NCBI database to query (e.g., "clinvar", "gds", "geoprofiles")
    result_formatter (callable): Function to format results from the database

    max_results (int): Maximum number of results to return
    verbose (bool): Whether to return verbose results
    
    Returns:
    dict: Dictionary containing both the structured query and the results
    """
    
    # Query NCBI API using the structured search term
    esearch_url = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
    esearch_params = {
        "db": database,
        "term": search_term,
        "retmode": "json",
        "retmax": 100,
        "usehistory": "y"  # Use history server to store results
    }
    
    # Get IDs of matching entries
    search_response = _query_rest_api(
        endpoint=esearch_url,
        method="GET",
        params=esearch_params,
        description="NCBI ESearch API query"
    )

    if not search_response["success"]:
        return search_response
    
    search_data = search_response["result"]
    
    # If we have results, fetch the details
    if "esearchresult" in search_data and int(search_data["esearchresult"]["count"]) > 0:
        # Extract WebEnv and query_key from the search results
        webenv = search_data["esearchresult"].get("webenv", "")
        query_key = search_data["esearchresult"].get("querykey", "")
        
        # Use WebEnv and query_key if available
        if webenv and query_key:
            # Get details using eSummary
            esummary_url = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi"
            esummary_params = {
                "db": database,
                "query_key": query_key,
                "WebEnv": webenv,
                "retmode": "json",
                "retmax": max_results
            }
            
            details_response = _query_rest_api(
                endpoint=esummary_url,
                method="GET",
                params=esummary_params,
                description="NCBI ESummary API query"
            )

            if not details_response["success"]:
                return details_response
            
            results = details_response["result"]
        
        else:
            # Fall back to direct ID fetch
            id_list = search_data["esearchresult"]["idlist"][:max_results]
            
            # Get details for each ID
            esummary_url = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi"
            esummary_params = {
                "db": database,
                "id": ",".join(id_list),
                "retmode": "json"
            }
            
            details_response = _query_rest_api(
                endpoint=esummary_url,
                method="GET",
                params=esummary_params,
                description="NCBI ESummary API query"
            )
            
            if not details_response["success"]:
                return details_response
            
            results = details_response["result"]
        
        # Format results using the provided formatter
        if result_formatter:
            formatted_results = result_formatter(results)
        else:
            formatted_results = results
        
        # Return the combined information
        return {
            "database": database,
            "query_interpretation": search_term,
            "total_results": int(search_data["esearchresult"]["count"]),
            "formatted_results": formatted_results
        }
    else:
        return {
            "database": database,
            "query_interpretation": search_term,
            "total_results": 0,
            "formatted_results": []
        }

def _format_query_results(result, options=None):
    """
    A general-purpose formatter for query function results to reduce output size.
    
    Parameters:
    result (dict): The original API response dictionary
    options (dict, optional): Formatting options including:
        - max_items (int): Maximum number of items to include in lists (default: 5)
        - max_depth (int): Maximum depth to traverse in nested dictionaries (default: 2)
        - include_keys (list): Only include these top-level keys (overrides exclude_keys)
        - exclude_keys (list): Exclude these keys from the output
        - summarize_lists (bool): Whether to summarize long lists (default: True)
        - truncate_strings (int): Maximum length for string values (default: 100)
    
    Returns:
    dict: A condensed version of the input results
    """
    def _format_value(value, depth, options):
        """
        Recursively format a value based on its type and formatting options.
        
        Parameters:
        value: The value to format
        depth (int): Current recursion depth
        options (dict): Formatting options
        
        Returns:
        Formatted value
        """
        # Base case: reached max depth
        if depth >= options['max_depth'] and (isinstance(value, dict) or isinstance(value, list)):
            if isinstance(value, dict):
                return {
                    '_summary': f'Nested dictionary with {len(value)} keys',
                    '_keys': list(value.keys())[:options['max_items']]
                }
            else:  # list
                return _summarize_list(value, options)
        
        # Process based on type
        if isinstance(value, dict):
            return _format_dict(value, depth, options)
        elif isinstance(value, list):
            return _format_list(value, depth, options)
        elif isinstance(value, str) and len(value) > options['truncate_strings']:
            return value[:options['truncate_strings']] + "... (truncated)"
        else:
            return value


    def _format_dict(d, depth, options):
        """Format a dictionary according to options."""
        result = {}
        
        # Filter keys based on include/exclude options
        keys_to_process = d.keys()
        if depth == 0 and options['include_keys']:  # Only apply at top level
            keys_to_process = [k for k in keys_to_process if k in options['include_keys']]
        elif depth == 0 and options['exclude_keys']:  # Only apply at top level
            keys_to_process = [k for k in keys_to_process if k not in options['exclude_keys']]
        
        # Process each key
        for key in keys_to_process:
            result[key] = _format_value(d[key], depth + 1, options)
        
        return result


    def _format_list(lst, depth, options):
        """Format a list according to options."""
        if options['summarize_lists'] and len(lst) > options['max_items']:
            return _summarize_list(lst, options)
        
        result = []
        for i, item in enumerate(lst):
            if i >= options['max_items']:
                remaining = len(lst) - options['max_items']
                result.append(f"... {remaining} more items (omitted)")
                break
            result.append(_format_value(item, depth + 1, options))
        
        return result


    def _summarize_list(lst, options):
        """Create a summary for a list."""
        if not lst:
            return []
        
        # Sample a few items
        sample = lst[:min(3, len(lst))]
        sample_formatted = [_format_value(item, options['max_depth'], options) for item in sample]
        
        # For homogeneous lists, provide type info
        if len(lst) > 0:
            item_type = type(lst[0]).__name__
            homogeneous = all(isinstance(item, type(lst[0])) for item in lst)
            type_info = f"all {item_type}" if homogeneous else "mixed types"
        else:
            type_info = "empty"
        
        return {
            '_summary': f"List with {len(lst)} items ({type_info})",
            '_sample': sample_formatted
        }

    if options is None:
        options = {}
    
    # Default options
    default_options = {
        'max_items': 5,
        'max_depth': 20,
        'include_keys': None,
        'exclude_keys': ['raw_response', 'debug_info', 'request_details'],
        'summarize_lists': True,
        'truncate_strings': 100
    }
    
    # Merge provided options with defaults
    for key, value in default_options.items():
        if key not in options:
            options[key] = value
    
    # Filter and format the result
    formatted = _format_value(result, 0, options)
    return formatted




# === 工具 3: UniProt 查询工具 ===
# 测试成功
# query:Find information about human insulin protein
class QueryUniProtInput(BaseModel):
    """
    UniProt 查询工具输入参数模型
    """
    prompt: Optional[str] = Field(None, description="自然语言查询，如: 'Find information about human insulin protein'")
    endpoint: Optional[str] = Field(None, description="UniProt API 端点 URL，可为完整或相对路径")
    max_results: int = Field(5, description="最多返回的结果数量")


def query_uniprot_database(prompt=None, endpoint=None, max_results=5):
    import os
    import json
    import pickle

    base_url = "https://rest.uniprot.org"

    if prompt is None and endpoint is None:
        return {"error": "Either a prompt or an endpoint must be provided"}

    if prompt:
        schema_path = os.path.join(os.path.dirname(__file__), "schema_db", "uniprot.pkl")

        with open(schema_path, "rb") as f:
            uniprot_schema = pickle.load(f)

        system_template = """
        You are a protein biology expert specialized in using the UniProt REST API.

        Based on the user's natural language request, determine the appropriate UniProt REST API endpoint and parameters.

        UNIPROT REST API SCHEMA:
        {schema}

        Your response should be a JSON object with the following fields:
        1. "full_url": The complete URL to query (including base URL, dataset, endpoint type, and parameters)
        2. "description": A brief description of what the query is doing

        SPECIAL NOTES:
        - Base URL is "https://rest.uniprot.org"
        - Search in reviewed (Swiss-Prot) entries first before using non-reviewed (TrEMBL) entries
        - Assume organism is human unless otherwise specified. Human taxonomy ID is 9606
        - Use gene_exact: for exact gene name searches
        - Use specific query fields like accession:, gene:, organism_id: in search queries
        - Use quotes for terms with spaces: organism_name:"Homo sapiens"

        Return ONLY the JSON object with no additional text.
        """

        claude_result = _query_claude_for_api(
            prompt=prompt,
            schema=uniprot_schema,
            system_template=system_template,
        )

        if not claude_result["success"]:
            return claude_result

        query_info = claude_result["data"]
        endpoint = query_info.get("full_url", "")
        description = query_info.get("description", "")

        if not endpoint:
            return {
                "error": "Failed to generate a valid endpoint from the prompt",
                "claude_response": claude_result.get("raw_response", "No response")
            }
    else:
        if endpoint.startswith("/"):
            endpoint = f"{base_url}{endpoint}"
        elif not endpoint.startswith("http"):
            endpoint = f"{base_url}/{endpoint.lstrip('/')}"
        description = "Direct query to provided endpoint"

    api_result = _query_rest_api(endpoint=endpoint, method="GET", description=description)
    
    # ---- 提取关键信息 ----

    try:
        #results = api_result.get("result", {}).get("results", [])
        #trimmed_results = []
        raw = api_result.get("result", {})
        # 根据接口类型拿到列表
        if isinstance(raw.get("results"), list):
            entries = raw["results"]
        else:
            # 对于 /uniprotkb/{accession} 直接返回的对象
            entries = [raw]
        # 然后再抽取：
        trimmed_results = []
        for item in entries[:max_results]:
            trimmed = {
                "UniProt Accession": item.get("primaryAccession"),
                "UniProt ID": item.get("uniProtkbId"),
                "Protein Name": item.get("proteinDescription", {}).get("recommendedName", {}).get("fullName", {}).get("value"),
                "Organism": item.get("organism", {}).get("scientificName"),
                "Taxonomy ID": item.get("organism", {}).get("taxonId"),
                "Gene Names": [gene["geneName"]["value"] for gene in item.get("genes", []) if "geneName" in gene],
            }
            trimmed_results.append(trimmed)

        return {
            "success": True,
            "query_info": {
                "endpoint": endpoint,
                "description": description
            },
            "results": trimmed_results
        }
 
    except Exception as e:
        return {
            "error": f"Failed to parse UniProt result: {e}",
            "raw": api_result
        }


# 注册 —— 这次 coroutine= 就可以用了
query_uniprot_tool = StructuredTool.from_function(
    func=query_uniprot_database,   # 现在真的是协程
    name=Tools.QUERY_UNIPROT,
   description="""
    【领域：生物】
    Query the UniProt REST API using either natural language or a direct endpoint.
    
    Returns:
    dict: Dictionary containing the query information and the UniProt API results
    
    Examples:
    - Natural language: query_uniprot(prompt="Find information about human insulin protein")
    - Direct endpoint: query_uniprot(endpoint="https://rest.uniprot.org/uniprotkb/P01308")
""",
    args_schema=QueryUniProtInput,
    metadata={"args_schema_json":QueryUniProtInput.schema()}
)



# === 工具 4: AlphaFold 查询与下载工具 ===

"""
query-1:“查询人胰岛素蛋白的预测结构”
{
  "uniprot_id": "P01308",
  "endpoint": "prediction"
}

query-2:“仅查询BRCA1蛋白中残基100-300的预测结构”
{
  "uniprot_id": "P38398",
  "endpoint": "prediction",
  "residue_range": "100-300"
}

"""
# 测试成功
class QueryAlphaFoldInput(BaseModel):
    """
    #AlphaFold 数据库查询工具输入参数模型
    """
    uniprot_id: str = Field(..., description="UniProt accession ID，例如: P12345")
    endpoint: str = Field("prediction", description="查询端点: prediction, summary, annotations")
    residue_range: Optional[str] = Field(None, description="残基范围，格式 'start-end'（可选）")
    download: bool = Field(False, description="是否下载结构文件")
    file_format: str = Field("pdb", description="下载文件格式: pdb 或 cif")
    model_version: str = Field("v4", description="AlphaFold 模型版本: v1/v2/v3/v4")
    model_number: int = Field(1, description="模型编号 (1-5)")

async def query_alphafold_coroutine(
    uniprot_id: str,
    endpoint: str = "prediction",
    residue_range: Optional[str] = None,
    download: bool = False,
    file_format: str = "pdb",
    model_version: str = "v4",
    model_number: int = 1
) -> Dict[str, Any]:
    """
    查询 AlphaFold 数据库并可选下载结构文件。
    返回字段示例：
    {
      "query_info": {...},
      "result": {...},
      "download": {...}  # 若下载
    }
    """
    import requests
    # 基础校验
    if not uniprot_id:
        return {"error": "UniProt ID 为必填"}
    if endpoint not in ["prediction", "summary", "annotations"]:
        return {"error": f"端点无效，须为 prediction/summary/annotations"}

    base_url = "https://alphafold.ebi.ac.uk/api"
    # 构造查询 URL
    if endpoint == "prediction":
        url = f"{base_url}/prediction/{uniprot_id}"
    elif endpoint == "summary":
        url = f"{base_url}/uniprot/summary/{uniprot_id}.json"
    else:
        url = f"{base_url}/annotations/{uniprot_id}" + (f"/{residue_range}" if residue_range else "")

    try:
        resp = requests.get(url)
        resp.raise_for_status()
        data = resp.json()

        result = {
            "query_info": {
                "uniprot_id": uniprot_id,
                "endpoint": endpoint,
                "residue_range": residue_range,
                "url": url
            },
            "result": data
        }

        # 如果需要下载，则获取文件并上传到 MinIO，返回文件 URL
        if download:
            ext = file_format.lower()
            filename = f"AF-{uniprot_id}-F{model_number}-model_{model_version}.{ext}"
            file_url = f"https://alphafold.ebi.ac.uk/files/{filename}"
            dl_resp = requests.get(file_url)
            if dl_resp.status_code == 200:
                content = dl_resp.content
                try:
                    upload_url = await upload_content_to_minio(
                        content=content,
                        file_name=filename,
                        file_extension=f".{ext}",
                        content_type="chemical/x-pdb" if ext == "pdb" else "application/octet-stream",
                        no_expired=True
                    )
                    result["download"] = {
                        "success": True,
                        "download_file_url": upload_url,
                        "source_url": file_url
                    }
                except Exception as e:
                    result["download"] = {
                        "success": False,
                        "error": f"上传失败: {str(e)}",
                        "source_url": file_url
                    }
            else:
                result["download"] = {
                    "success": False,
                    "error": f"下载失败: HTTP {dl_resp.status_code}",
                    "source_url": file_url
                }
        return result

    except requests.RequestException as e:
        return {
            "error": f"AlphaFold API 错误: {str(e)}",
            "query_info": {"uniprot_id": uniprot_id, "endpoint": endpoint, "url": url}
        }
    except Exception as e:
        return {
            "error": f"未知错误: {str(e)}",
            "query_info": {"uniprot_id": uniprot_id, "endpoint": endpoint}
        }


# 创建 QueryAlphaFold 工具
query_alphafold_tool = StructuredTool.from_function(
    coroutine=query_alphafold_coroutine,
    name=Tools.QUERY_ALPHAFOLD,
   description="""
    【领域：生物】
    查询 AlphaFold 数据库并可选下载结构文件。
    注意：如果是查询蛋白质pdb结构文件相关任务，请你优先使用该工具！
    输出内容:
      - query_info: 查询元信息，包括调用 API 的端点、使用的 UniProt ID 等
      - result: 预测结果列表（通常只包含一个模型），包含以下字段：
          - entryId: AlphaFold 模型条目ID
          - gene: 基因名（如 ADORA2A）
          - uniprotId/uniprotAccession: UniProt 标识
          - uniprotSequence: 氨基酸序列
          - modelCreatedDate / sequenceVersionDate
          - structure file URLs:
              - pdbUrl: PDB 格式结构文件
              - cifUrl: mmCIF 格式结构文件
              - bcifUrl: Binary CIF 文件
          - paeImageUrl: 预测比对误差 (PAE) 图像
          - paeDocUrl: PAE 数值 JSON 文件
          - amAnnotationsUrl / Hg19 / Hg38: 氨基酸替代注释（通用于突变研究）
          - isReviewed: 是否为已审核 UniProt 条目
          - isReferenceProteome: 是否来自参考蛋白质组
      - download: 如果下载选项启用，包含:
          - download_file_url: 本地中转服务器上的结构文件下载链接
          - source_url: 原始 AlphaFold 文件地址
    """,
    args_schema=QueryAlphaFoldInput,
    metadata={"args_schema_json":QueryAlphaFoldInput.schema()}
)

# === 工具 5: RCSB PDB 文献搜索工具(query_pdb) ===
# query:请你搜索6ZRY  pdb的文件，用query_pdb工具
# 测试成功
class QueryPDBInput(BaseModel):
    """
    RCSB PDB 数据库查询输入参数模型

    可使用自然语言 `prompt` 或结构化 JSON `query`，推荐仅使用其一。
    如果同时提供，将优先使用结构化查询。
    """
    prompt: Optional[str] = Field(
        default=None,
        description="自然语言查询，例如：'Find structures of human insulin'。当 query 提供时将被忽略"
    )
    query: Optional[Dict[str, Any]] = Field(
        default=None,
        description="结构化 JSON 查询，符合 RCSB Search API 格式。优先级高于 prompt"
    )
    max_results: int = Field(
        default=3,
        description="返回的最大结果数，默认值为 3"
    )


def query_pdb_coroutine(
    prompt: Optional[str] = None,
    query: Optional[Dict[str, Any]] = None,
    max_results: int = 3
) -> Dict[str, Any]:
    """
    使用自然语言或结构化 JSON 查询 RCSB PDB Search API。
    参数：
      - prompt: 自然语言描述查询，优先级低于 query
      - query: Search API 结构化查询对象
      - max_results: 返回条目数
    返回：
      - query_json: 最终发送的查询对象
      - results: API 返回的搜索结果 JSON
    """
    from os import path
    import json

    # 默认检索参数
    return_type = "entry"
    search_service = "full_text"

    # 生成结构化查询
    if prompt and not query:
        # 加载 schema
        schema_path = path.join(path.dirname(__file__), "schema_db", "pdb.pkl")
        with open(schema_path, "rb") as f:
            pdb_schema = pickle.load(f)
        #system_template = "基于自然语言生成 RCSB PDB Search API 查询 JSON，返回 JSON 对象。"
        system_template = """
        You are a structural biology expert that creates precise RCSB PDB Search API queries based on natural language requests.
        
        SEARCH API SCHEMA:
        {schema}
        
        IMPORTANT GUIDELINES:
        1. Choose the appropriate search_service based on the query:
           - Use "text" for attribute-specific searches (REQUIRES attribute, operator, and value)
           - Use "full_text" for general keyword searches across multiple fields
           - Use appropriate specialized services for sequence, structure, motif searches
        
        2. For "text" searches, you MUST specify:
           - attribute: The specific field to search (use common_attributes from schema)
           - operator: The comparison method (exact_match, contains_words, less_or_equal, etc.)
           - value: The search term or value
        
        3. For "full_text" searches, only specify:
           - value: The search term(s)
        
        4. For combined searches, use "group" nodes with logical_operator ("and" or "or")
        
        5. Always specify the appropriate return_type based on what the user is looking for
        
        Generate a well-formed Search API query JSON object. Return ONLY the JSON with no additional explanation.
        """

        claude_res = _query_claude_for_api(
            prompt=prompt,
            schema=pdb_schema,
            system_template=system_template,
        )
        print("\n")
        print("#####claude_res #####",claude_res)
        print("\n")
        if not claude_res.get("success", False):
            return {"error": claude_res.get("error"), "claude_response": claude_res.get("raw_response")}
        query_json = claude_res.get("data", {})
    else:
        query_json = query or {
            "query": {"type": "terminal", "service": search_service, "parameters": {"value": prompt or ""}},
            "return_type": return_type
        }

    # 设置返回类型与分页
    query_json.setdefault("return_type", return_type)
    ro = query_json.setdefault("request_options", {})
    ro.setdefault("paginate", {"start": 0, "rows": max_results})

    # 调用 Search API
    search_url = "https://search.rcsb.org/rcsbsearch/v2/query"
    api_res =  _query_rest_api(
        endpoint=search_url,
        method="POST",
        json_data=query_json,
        description="PDB Search API query"
    )
    print("\n")
    print("#####api_res#####",api_res)
    print("\n")
    return {"query_json": query_json, "results": api_res}

# 创建 QueryPDB 工具
query_pdb_tool = StructuredTool.from_function(
    func = query_pdb_coroutine,
    name=Tools.QUERY_PDB,
   description="""
    【领域：生物】
    用于从 RCSB PDB（Protein Data Bank）数据库中检索蛋白质三维结构信息的专业查询工具。

    支持两种查询方式：
    1. **自然语言查询**（prompt）：适合模糊搜索或通用语义查询，例如 “Find structures of SARS-CoV-2 spike protein”；
    2. **结构化 JSON 查询**（query）：基于 RCSB PDB 官方 Search API 构造的查询体，推荐用于精确检索（如指定 PDB ID、蛋白名、物种、分辨率范围等）。

     返回字段：
    - **query_json**：最终用于提交查询的结构化 JSON（即使是从 prompt 自动生成）；
    - **results**：一个包含结构检索结果的列表，每项包括：
        - **entry_id**（如 6ZRY）
        - **score**（匹配评分）
        - **related metadata**（如结构标题、发布日期等，依实现而定）

    常见用途：
    - 精确查找指定蛋白结构（如通过 PDB ID）；
    - 获取某一蛋白在不同物种中的结构；
    - 搜索包含特定配体或构象的蛋白复合物。
    """
,
    args_schema=QueryPDBInput,
    metadata={"args_schema_json":QueryPDBInput.schema()}
)

# === 工具 6: PDB 详细信息与结构下载工具 ===
class QueryPDBIdentifiersInput(BaseModel):
    """
    获取 PDB 条目详细数据及可选下载结构文件的工具输入模型
    """
    identifiers: List[str] = Field(..., description="PDB 条目列表，例如: ['1TUP', '4HHB'] 或 带后缀实体 ID")
    return_type: str = Field("entry", description="返回类型: entry, polymer_entity, assembly 等")
    download: bool = Field(False, description="是否下载结构文件至 MinIO")
    attributes: Optional[List[str]] = Field(None, description="筛选返回的特定字段列表，如 'rcsb_entry_info.dates.release_date'")

async def query_pdb_identifiers_coroutine(
    identifiers: List[str],
    return_type: str = "entry",
    download: bool = False,
    attributes: Optional[List[str]] = None
) -> Dict[str, Any]:
    """
    基于 PDB ID 列表获取详细数据，并可选下载结构文件。
    返回：
      - detailed_results: 每条包含 identifier, data, download_file_url (如下载)
    """
    import os, requests

    if not identifiers:
        return {"error": "未提供任何 identifiers"}
    detailed = []
    for iden in identifiers:
        try:
            # 构造 Data API URL
            entry, sep, tail = iden.partition('_')
            if return_type == "entry":
                url = f"https://data.rcsb.org/rest/v1/core/entry/{entry}"
            elif return_type == "polymer_entity":
                eid, ent = iden.split('_')
                url = f"https://data.rcsb.org/rest/v1/core/polymer_entity/{eid}/{ent}"
            else:
                url = f"https://data.rcsb.org/rest/v1/core/{return_type}/{entry}"
            resp = requests.get(url)
            resp.raise_for_status()
            data = resp.json()
            # 筛选属性
            if attributes:
                filt = {}
                for attr in attributes:
                    parts = attr.split('.')
                    cur = data
                    try:
                        for p in parts:
                            cur = cur[p]
                        filt[attr] = cur
                    except Exception:
                        filt[attr] = None
                data = filt
            detailed.append({"identifier": iden, "data": data})
        except Exception as e:
            detailed.append({"identifier": iden, "error": str(e)})
    result = {"detailed_results": detailed}
    # 下载 PDB 文件并上传
    if download:
        for item in detailed:
            if "data" in item:
                pdb_id = item["identifier"].split('_')[0]
                pdb_url = f"https://files.rcsb.org/download/{pdb_id}.pdb"
                r = requests.get(pdb_url)
                if r.status_code == 200:
                    content = r.content
                    filename = f"{pdb_id}.pdb"
                    try:
                        file_url = await upload_content_to_minio(
                            content=content,
                            file_name=filename,
                            file_extension=".pdb",
                            content_type="chemical/x-pdb",
                            no_expired=True
                        )
                        item["download_file_url"] = file_url
                    except S3Error as e:
                        item["download_error"] = f"上传失败: {e.message}"
    return result

# # 创建 QueryPDBIdentifiers 工具
query_pdb_identifiers_tool = StructuredTool.from_function(
   coroutine=query_pdb_identifiers_coroutine,
    name=Tools.QUERY_PDB_IDENTIFIERS,
    description="""
    【领域：生物】
     基于 PDB ID 列表获取详细数据，并可选下载结构文件。
     参数：
       - identifiers: PDB 条目列表
       - return_type: 返回数据类型
       - download: 是否下载并上传结构文件
      - attributes: 筛选字段列表
     返回：
       - detailed_results: 包含 identifier, data, download_file_url 等
    注意：如果该工具搜索不到相关信息，请你调用”AlphaFold数据库查询“工具
     """,
     args_schema=QueryPDBIdentifiersInput,
     metadata={"args_schema_json":QueryPDBIdentifiersInput.schema()}
 )




# === 工具 7: GWAS Catalog 查询工具 ===
# query:有哪些基因变异与乳腺癌风险显著相关？
# 测试成功
class QueryGWASCatalogInput(BaseModel):
    """
    GWAS Catalog 查询工具输入模型
    """
    prompt: Optional[str] = Field(None, description="自然语言查询，如: 'Find GWAS studies related to Type 2 diabetes'")
    endpoint: Optional[str] = Field(None, description="直接API端点，如: 'studies', 'associations'")
    max_results: int = Field(3, description="最多返回记录数")
    verbose: bool = Field(False, description="是否返回详细结果")

def query_gwas_catalog(
    prompt: Optional[str] = None,
    endpoint: Optional[str] = None,
    max_results: int = 3,
    verbose: bool = False
) -> Dict[str, Any]:
    """
    使用自然语言或指定端点查询 GWAS Catalog API。
    返回：
      - 如 verbose=False，仅返回核心结果；
      - verbose=True 时附加全文响应。
    """
    base_url = "https://www.ebi.ac.uk/gwas/rest/api"
    # 验证输入
    if not prompt and not endpoint:
        return {"error": "必须提供 prompt 或 endpoint"}
    # 生成或使用端点
    params = {"size": max_results}
    description = ""
    if prompt:
        schema_path = os.path.join(os.path.dirname(__file__), "schema_db", "gwas_catalog.pkl")
        with open(schema_path, "rb") as f:
            gwas_schema = pickle.load(f)
        template = """
        You are a genomics expert specialized in using the GWAS Catalog API.
        
        Based on the user's natural language request, determine the appropriate GWAS Catalog API endpoint and parameters.
        
        GWAS CATALOG API SCHEMA:
        {schema}
        
        Your response should be a JSON object with the following fields:
        1. "endpoint": The API endpoint to query (e.g., "studies", "associations")
        2. "params": An object containing query parameters specific to the endpoint
        3. "description": A brief description of what the query is doing
        
        SPECIAL NOTES:
        - For disease/trait searches, consider using the "EFO" identifiers when possible
        - Common endpoints include: "studies", "associations", "singleNucleotidePolymorphisms", "efoTraits"
        - For pagination, use "size" and "page" parameters
        - For filtering by p-value, use "pvalueMax" parameter
        - GWAS Catalog uses a HAL-based REST API
        
        Return ONLY the JSON object with no additional text.
        """
        claude_res =  _query_claude_for_api(
            prompt=prompt, schema=gwas_schema,
            system_template=template,
        )
        if not claude_res.get("success", False):
            return claude_res
        info = claude_res.get("data", {})
        endpoint = info.get("endpoint", endpoint)
        params = info.get("params", params)
        description = info.get("description", "")
        if not endpoint:
            return {"error": "从 prompt 无法生成 endpoint", "claude_response": claude_res.get("raw_response")}
    else:
        description = f"直接查询端点 {endpoint}"  # endpoint 已由外部指定
    # 去除前导 '/'
    endpoint = endpoint.lstrip('/')
    url = f"{base_url}/{endpoint}"
    api_res =  _query_rest_api(endpoint=url, method="GET",
                                    params=params, description=description)
    # 根据 verbose 选择返回
    if not verbose and isinstance(api_res, dict) and api_res.get("result"):
        return _format_query_results(api_res["result"])
    return api_res

# 注册 GWAS Catalog 工具
gwas_catalog_tool = StructuredTool.from_function(
    func=query_gwas_catalog,
    name=Tools.QUERY_GWAS_CATALOG,
   description="""
    【领域：生物】
    GWAS目录是遗传学研究中的重要资源，该工具能够快速检索全基因组关联研究的结果，对于研究基因与疾病之间的关联、揭示遗传疾病的发病机制具有重要价值。
    查询 GWAS Catalog API，可用自然语言或直接端点。
    返回：
      - API 响应或格式化结果
    """,
    args_schema=QueryGWASCatalogInput,
    metadata={"args_schema_json":QueryGWASCatalogInput.schema()}
)


# === 工具 8: ClinVar 查询工具 ===
# query:查询 rs121913529 的临床意义和关联疾病。
# 测试成功
class QueryClinVarInput(BaseModel):
    """
    ClinVar 查询工具输入模型
    """
    prompt: Optional[str] = Field(None, description="自然语言查询，如: 'Find pathogenic BRCA1 variants'")
    search_term: Optional[str] = Field(None, description="直接使用的 ClinVar 搜索语句")

    max_results: int = Field(3, description="最多返回记录数")

def query_clinvar_coroutine(
    prompt: Optional[str] = None,
    search_term: Optional[str] = None,

    max_results: int = 1
) -> Dict[str, Any]:
    """
    将自然语言转换为 ClinVar 搜索语句并查询 NCBI ClinVar 数据库。
    返回：structured query 和查询结果。
    """
    if not prompt and not search_term:
        return {"error": "必须提供 prompt 或 search_term"}
    if prompt:
        schema_path = os.path.join(os.path.dirname(__file__), "schema_db", "clinvar.pkl")
        with open(schema_path, "rb") as f:
            clinvar_schema = pickle.load(f)
        template = """
        You are a genetics research assistant that helps convert natural language queries into structured ClinVar search queries.
        
        Based on the user's natural language request, you will generate a structured search for the ClinVar database.
        
        Output only a JSON object with the following fields:
        1. "search_term": The exact search query to use with the ClinVar API
        
        IMPORTANT: Your response must ONLY contain a JSON object with the search term field.

        Your "search_term" MUST strictly follow these ClinVar search syntax rules/tags:

        {schema}

        For combining terms: Use AND, OR, NOT (must be capitalized)
        For complex logic: Use parentheses
        For terms with multiple words: use double quotes escaped with a backslash or underscore (e.g. breast_cancer[dis] or \"breast cancer\"[dis])
        Example: "BRCA1[gene] AND (pathogenic[clinsig] OR likely_pathogenic[clinsig])"


        EXAMPLES OF CORRECT QUERIES:
        - For "pathogenic BRCA1 variants": "BRCA1[gene] AND clinsig_pathogenic[prop]"
        - For "Specific RS": "rs6025[rsid]"
        - For "Combined search with multiple criteria": "BRCA1[gene] AND origin_germline[prop]"
        - For "Find variants in a specific genomic region": "17[chr] AND 43000000:44000000[chrpos37]"
        - If query asks for pathogenicity of a variant, it's asking for all possible germline classifications of the variant, so just [gene] AND [variant] is needed
        """
        claude_res = _query_claude_for_api(
            prompt=prompt, schema=clinvar_schema,
            system_template=template,
        )
        if not claude_res.get("success", False):
            return claude_res
        search_term = claude_res.get("data", {}).get("search_term")
        if not search_term:
            return {"error": "从 prompt 无法生成 search_term"}
        # === 查询数据库 ===
    api_res = _query_ncbi_database(
        database="clinvar",
        search_term=search_term,
        max_results=max_results
    )

    # === 👇 裁剪过长输出，统一返回格式 ===
    if isinstance(api_res, dict):
        text = json.dumps(api_res, ensure_ascii=False, indent=2)
    else:
        text = str(api_res)

    MAX_OUTPUT_LEN = 10000
    if len(text) > MAX_OUTPUT_LEN:
        text = (
            "The output is too long to be added to context.\n"
            f"Here are the first {MAX_OUTPUT_LEN // 1000}K characters...\n\n"
            + text[:MAX_OUTPUT_LEN]
        )

    return {
        "success": True,
        "search_term": search_term,
        "result": text
    }


# 注册 ClinVar 工具
clinvar_tool = StructuredTool.from_function(
    func=query_clinvar_coroutine,
    name=Tools.QUERY_CLINVAR,
   description="""
    【领域：生物】
    ClinVar是临床遗传学领域的重要数据库，该工具能够快速检索遗传变异的临床相关信息，对于遗传病诊断、基因咨询和临床研究具有重要价值。
    查询 NCBI ClinVar 数据库，可使用自然语言或直接 search_term。
    返回：查询结果 JSON。
    """,
    args_schema=QueryClinVarInput,
    metadata={"args_schema_json":QueryClinVarInput.schema()}
)


#  === 工具 9: GEO 查询工具 ===
# query:查询肝组织的基因表达数据集。
#“查看TNF-alpha刺激下单核细胞的表达数据。”

#“GEO中有没有使用紫外线照射处理的人角质细胞表达谱数据？”

#“检索高糖培养条件下胰岛β细胞的转录组数据。”
# 测试成功
class QueryGEOInput(BaseModel):
    """
    GEO 查询工具输入模型
    """
    prompt: Optional[str] = Field(None, description="自然语言查询，如: 'Find RNA-seq datasets for breast cancer'")
    search_term: Optional[str] = Field(None, description="直接使用的 GEO 搜索语句")

    max_results: int = Field(3, description="最多返回记录数")

def query_geo_coroutine(
    prompt: Optional[str] = None,
    search_term: Optional[str] = None,

    max_results: int = 3
) -> Dict[str, Any]:
    """
    将自然语言转换为 GEO 搜索语句并查询 NCBI GEO 数据库。
    返回：查询结果 JSON。
    """
    if not prompt and not search_term:
        return {"error": "必须提供 prompt 或 search_term"}
    if prompt:
        schema_path = os.path.join(os.path.dirname(__file__), "schema_db", "geo.pkl")
        with open(schema_path, "rb") as f:
            geo_schema = pickle.load(f)
        template = """
        You are a bioinformatics research assistant that helps convert natural language queries into structured GEO (Gene Expression Omnibus) search queries.
        
        Based on the user's natural language request, you will generate a structured search for the GEO database.
        
        Output only a JSON object with the following fields:
        1. "search_term": The exact search query to use with the GEO API
        2. "database": The specific GEO database to search (either "gds" for GEO DataSets or "geoprofiles" for GEO Profiles)
        
        IMPORTANT: Your response must ONLY contain a JSON object with the required fields.

        Your "search_term" MUST strictly follow these GEO search syntax rules/tags:
        
        {schema}

        For combining terms: Use AND, OR, NOT (must be capitalized)
        For complex logic: Use parentheses
        For terms with multiple words: use double quotes or underscore (e.g. "breast cancer"[Title])
        Date ranges use colon format: 2015/01:2020/12[PDAT]
        
        Choose the appropriate database based on the user's query:
        - gds: GEO DataSets (contains Series, Datasets, Platforms, Samples metadata)
        - geoprofiles: GEO Profiles (contains gene expression data)
        
        If database isn't clearly specified, default to "gds" as it contains most common experiment metadata.

        EXAMPLES OF CORRECT OUTPUTS:
        - For "RNA-seq data in breast cancer": {"search_term": "RNA-seq AND breast cancer AND gse[ETYP]", "database": "gds"}
        - For "Mouse microarray data from 2020": {"search_term": "Mus musculus[ORGN] AND 2020[PDAT] AND microarray AND gse[ETYP]", "database": "gds"}
        - For "Expression profiles of TP53 in lung cancer": {"search_term": "TP53[Gene Symbol] AND lung cancer", "database": "geoprofiles"}
        """
        claude_res =  _query_claude_for_api(
            prompt=prompt, schema=geo_schema,
            system_template=template,
        )
        if not claude_res.get("success", False):
            return claude_res
        data = claude_res.get("data", {})
        search_term = data.get("search_term")
        database = data.get("database", "gds")
        if not search_term:
            return {"error": "从 prompt 无法生成 search_term"}
    else:
        database = "gds"
    return  _query_ncbi_database(database=database,
                                     search_term=search_term,
                                     max_results=max_results)

# 注册 GEO 工具
geo_tool = StructuredTool.from_function(
    func=query_geo_coroutine,
    name=Tools.QUERY_GEO,
   description="""
    【领域：生物】
    GEO是基因表达数据的重要数据库，该工具能够快速检索基因表达数据，对于基因表达谱分析、疾病相关基因研究和生物标志物发现具有重要意义。
    查询 NCBI GEO 数据库，可使用自然语言或直接 search_term。
    返回：查询结果 JSON。
    """,
    args_schema=QueryGEOInput,
    metadata={"args_schema_json":QueryGEOInput.schema()}
)


# === 工具 10: dbSNP 查询工具 ===
# query:在BRCA1基因中常见的SNP有哪些？
# 搜索与2型糖尿病显著相关的dbSNP条目。
# 请查找第11号染色体上位置为chr11:5227002的SNP信息。
# 测试成功
class QueryDbSNPInput(BaseModel):
    """
    dbSNP 查询工具输入模型
    """
    prompt: Optional[str] = Field(None, description="自然语言查询，如: 'Find pathogenic variants in BRCA1'")
    search_term: Optional[str] = Field(None, description="直接使用的 dbSNP 搜索语句")

    max_results: int = Field(3, description="最多返回记录数")

def query_dbsnp_coroutine(
    prompt: Optional[str] = None,
    search_term: Optional[str] = None,

    max_results: int = 3
) -> Dict[str, Any]:
    """
    将自然语言转换为 dbSNP 搜索语句并查询 NCBI dbSNP 数据库。
    返回：查询结果 JSON。
    """
    if not prompt and not search_term:
        return {"error": "必须提供 prompt 或 search_term"}
    if prompt:
        schema_path = os.path.join(os.path.dirname(__file__), "schema_db", "dbsnp.pkl")
        with open(schema_path, "rb") as f:
            dbsnp_schema = pickle.load(f)
        template = """
        You are a genetics research assistant that helps convert natural language queries into structured dbSNP search queries.
        
        Based on the user's natural language request, you will generate a structured search for the dbSNP database.
        
        Output only a JSON object with the following fields:
        1. "search_term": The exact search query to use with the dbSNP API
        
        IMPORTANT: Your response must ONLY contain a JSON object with the search term field.

        Your "search_term" MUST strictly follow these dbSNP search syntax rules/tags:

        {schema}

        For combining terms: Use AND, OR, NOT (must be capitalized)
        For complex logic: Use parentheses
        For terms with multiple words: use double quotes (e.g. "breast cancer"[Disease Name])
        
        EXAMPLES OF CORRECT QUERIES:
        - For "pathogenic variants in BRCA1": "BRCA1[Gene Name] AND pathogenic[Clinical Significance]"
        - For "specific SNP rs6025": "rs6025[rs]"
        - For "SNPs in a genomic region": "17[Chromosome] AND 41196312:41277500[Base Position]"
        - For "common SNPs in EGFR": "EGFR[Gene Name] AND common[COMMON]"
        """
        claude_res = _query_claude_for_api(
            prompt=prompt, schema=dbsnp_schema,
            system_template=template,
        )
        if not claude_res.get("success", False):
            return claude_res
        search_term = claude_res.get("data", {}).get("search_term")
        if not search_term:
            return {"error": "从 prompt 无法生成 search_term"}
    return  _query_ncbi_database(database="snp",
                                      search_term=search_term,
                                      max_results=max_results)

# 注册 dbSNP 工具
dbsnp_tool = StructuredTool.from_function(
    func=query_dbsnp_coroutine,
    name=Tools.QUERY_DBSNP,
   description="""
    【领域：生物】
    dbSNP是单核苷酸多态性（SNP）数据库，该工具能够快速检索SNP信息，对于遗传学研究、基因组学分析和疾病关联研究具有基础性的重要作用。
    Query the NCBI dbSNP database using natural language or a direct search term.
    
    Returns:
    dict: Dictionary containing the query results or error information
    
    Examples:
    - Natural language: query_dbsnp("Find pathogenic variants in BRCA1")
    - Direct search: query_dbsnp(search_term="BRCA1[Gene Name] AND pathogenic[Clinical Significance]")
    """,
    args_schema=QueryDbSNPInput,
    metadata={"args_schema_json":QueryDbSNPInput.schema()}
)


# === 工具 11: UCSC 查询工具 ===
# query:查询TP53基因在hg38中的基因结构和外显子位置。
# 测试成功。
class QueryUCSCInput(BaseModel):
    """
    UCSC Genome Browser 查询工具输入模型
    """
    prompt: Optional[str] = Field(None, description="自然语言查询，如: 'Get DNA sequence of chrM 1-100'")
    endpoint: Optional[str] = Field(None, description="完整 URL 或相对端点字符串")
    verbose: bool = Field(True, description="是否返回详细结果")

def query_ucsc_coroutine(
    prompt: Optional[str] = None,
    endpoint: Optional[str] = None,
    verbose: bool = True
) -> Dict[str, Any]:
    """
    使用自然语言或端点查询 UCSC Genome Browser API。
    返回：API 响应或格式化结果。
    """
    base_url = "https://api.genome.ucsc.edu"
    if not prompt and not endpoint:
        return {"error": "必须提供 prompt 或 endpoint"}
    description = ""
    if prompt:
        schema_path = os.path.join(os.path.dirname(__file__), "schema_db", "ucsc.pkl")
        with open(schema_path, "rb") as f:
            ucsc_schema = pickle.load(f)
        template = """
        You are a genomics expert specialized in using the UCSC Genome Browser API.
        
        Based on the user's natural language request, determine the appropriate UCSC Genome Browser API endpoint and parameters.
        
        UCSC GENOME BROWSER API SCHEMA:
        {schema}
        
        Your response should be a JSON object with the following fields:
        1. "full_url": The complete URL to query (including the base URL "https://api.genome.ucsc.edu" and all parameters)
        2. "description": A brief description of what the query is doing
        
        SPECIAL NOTES:
        - For chromosome names, always include the "chr" prefix (e.g., "chr1", "chrX", "chrM")
        - Genomic positions are 0-based (first base is position 0)
        - For "start" and "end" parameters, both must be provided together
        - The "maxItemsOutput" parameter can be used to limit the amount of data returned
        - Common genomes include: "hg38" (human), "mm39" (mouse), "danRer11" (zebrafish)
        - For sequence data, use "getData/sequence" endpoint
        - For chromosome listings, use "list/chromosomes" endpoint
        - For available genomes, use "list/ucscGenomes" endpoint
        
        Return ONLY the JSON object with no additional text.
        """
        claude_res = _query_claude_for_api(
            prompt=prompt, schema=ucsc_schema,
            system_template=template,
        )
        if not claude_res.get("success", False):
            return claude_res
        info = claude_res.get("data", {})
        endpoint = info.get("full_url")
        description = info.get("description", "")
        if not endpoint:
            return {"error": "从 prompt 无法生成 full_url"}
    else:
        endpoint = endpoint if endpoint.startswith("http") else f"{base_url}/{endpoint.lstrip('/')}"
        description = "直接查询 UCSC API"
    api_res = _query_rest_api(endpoint=endpoint, method="GET", description=description)

    if not verbose and api_res.get("result"):
        result = _format_query_results(api_res["result"])
    else:
        result = api_res

    # === 👇 加入 10000 字符限制处理 ===
    if isinstance(result, dict):
        text = json.dumps(result, ensure_ascii=False)
    else:
        text = str(result)

    if len(text) > 10000:
        text = (
            "The output is too long to be added to context. "
            "Here are the first 10K characters...\n\n" + text[:10000]
        )

    return text

# 注册 UCSC 工具
ucsc_tool = StructuredTool.from_function(
    func=query_ucsc_coroutine,
    name=Tools.QUERY_UCSC,
   description="""
    【领域：生物】
    UCSC基因组浏览器是基因组学研究中的重要工具，该工具能够快速检索基因组数据，包括基因注释、基因组结构和表观遗传学信息等。
    Query the UCSC Genome Browser API using natural language or a direct endpoint.
    
    Returns:
    dict: Dictionary containing the query results or error information
    
    Examples:
    - Natural language: query_ucsc("Get DNA sequence of chromosome M positions 1-100 in human genome")
    - Direct endpoint: query_ucsc(endpoint="https://api.genome.ucsc.edu/getData/sequence?genome=hg38&chrom=chrM&start=1&end=100")
    """,
    args_schema=QueryUCSCInput,
    metadata={"args_schema_json":QueryUCSCInput.schema()}
)

##########0722添加#############
# === 工具 12: KEGG API 查询工具 ===
# 测试失败，api无返回结果

class QueryKEGGInput(BaseModel):
    """
    KEGG API 查询工具输入模型
    """
    prompt: Optional[str] = Field(
        None,
        description="自然语言查询，如: 'Find human pathways related to glycolysis'"
    )
    endpoint: Optional[str] = Field(
        None,
        description="直接使用的 KEGG REST API 端点（可选），如: 'get/hsa:672'"
    )

    verbose: bool = Field(
        True,
        description="是否返回原始 API 响应；若 False，则仅返回格式化结果"
    )

def query_kegg_coroutine(
    prompt: Optional[str] = None,
    endpoint: Optional[str] = None,

    verbose: bool = True
) -> Dict[str, Any]:
    """
    将自然语言 prompt 转换为结构化的 KEGG API 请求并执行查询。

    如果提供了 prompt，则调用 Claude 将其转换为 KEGG REST API 端点；
    否则直接使用 endpoint 调用。

    返回值：
      - success 的原始 API 响应或格式化结果
      - error 信息（若出错）
    """
    base_url = "https://rest.kegg.jp"

    # 必须至少提供 prompt 或 endpoint
    if not prompt and not endpoint:
        return {"error": "Either a prompt or an endpoint must be provided"}

    description = ""
    # 通过 LLM 生成 endpoint
    if prompt:
        schema_path = os.path.join(os.path.dirname(__file__), "schema_db", "kegg.pkl")
        with open(schema_path, "rb") as f:
            kegg_schema = pickle.load(f)

        system_template = """
        You are a bioinformatics expert that helps convert natural language queries into KEGG API requests.
        
        Based on the user's natural language request, you will generate a structured query for the KEGG API.
        
        The KEGG API has the following general form:
        https://rest.kegg.jp/<operation>/<argument>[/<argument2>[/<argument3> ...]]
        
        Where <operation> can be one of: info, list, find, get, conv, link, ddi
        
        Here is the schema of available operations, databases, and other details:
        {schema}
        
        Output only a JSON object with the following fields:
        1. "full_url": The complete URL to query (including the base URL "https://rest.kegg.jp")
        2. "description": A brief description of what the query is doing
        
        IMPORTANT: Your response must ONLY contain a JSON object with the required fields.
        
        EXAMPLES OF CORRECT OUTPUTS:
        - For "Find information about glycolysis pathway": {{"full_url": "https://rest.kegg.jp/info/pathway/hsa00010", "description": "Finding information about the glycolysis pathway"}}
        - For "Get information about the human BRCA1 gene": {{"full_url": "https://rest.kegg.jp/get/hsa:672", "description": "Retrieving information about BRCA1 gene in human"}}
        - For "List all human pathways": {{"full_url": "https://rest.kegg.jp/list/pathway/hsa", "description": "Listing all human-specific pathways"}}
        - For "Convert NCBI gene ID 672 to KEGG ID": {{"full_url": "https://rest.kegg.jp/conv/genes/ncbi-geneid:672", "description": "Converting NCBI Gene ID 672 to KEGG gene identifier"}}
        """
        claude_res = _query_claude_for_api(
            prompt=prompt,
            schema=kegg_schema,
            system_template=system_template,

        )
        if not claude_res.get("success", False):
            return claude_res

        info = claude_res["data"]
        endpoint = info.get("full_url")
        description = info.get("description", "")
        if not endpoint:
            return {"error": "Failed to generate a valid endpoint from the prompt"}

    # 构造完整 URL
    if endpoint:
        if endpoint.startswith("/"):
            full_url = f"{base_url}{endpoint}"
        elif endpoint.startswith("http"):
            full_url = endpoint
        else:
            full_url = f"{base_url}/{endpoint.lstrip('/')}"
        if not description:
            description = "Direct KEGG API query"
    else:
        return {"error": "No endpoint available to call"}

    # 执行 REST 调用
    api_res = _query_rest_api(endpoint=full_url, method="GET", description=description)

    # 根据 verbose 决定返回格式
    if not verbose and api_res.get("success") and "result" in api_res:
        return _format_query_results(api_res["result"])
    return api_res

# 注册 KEGG 工具
kegg_tool = StructuredTool.from_function(
    func=query_kegg_coroutine,
    name=Tools.QUERY_KEGG,
   description="""
    【领域：生物】
    Take a natural language prompt and convert it to a structured KEGG API query.
    
    Returns:
    dict: Dictionary containing both the structured query and the KEGG results
    """,
    args_schema=QueryKEGGInput,
    metadata={"args_schema_json":QueryKEGGInput.schema()}
)



# === 工具 13: STRING 蛋白互作数据库 查询工具 ===
# 测试成功
#query:展示人类 TP53 与 MDM2 之间的蛋白互作网络，并返回可视化图像链接。
class QuerySTRINGDBInput(BaseModel):
    """
    STRING 蛋白互作数据库查询工具输入模型
    """
    prompt: Optional[str] = Field(
        None,
        description="自然语言查询，如: 'Show protein interactions for BRCA1 and BRCA2 in humans'"
    )
    endpoint: Optional[str] = Field(
        None,
        description="完整或相对的 STRING API 端点，如: 'api/json/network?identifiers=BRCA1,BRCA2&species=9606'"
    )

    # #download_image: bool = Field(
    #     False,
    #     description="是否下载图片结果（针对 image/svg 输出）"
    # )
    verbose: bool = Field(
        True,
        description="是否返回完整 API 响应；若 False，仅返回格式化结果"
    )

async def query_stringdb_coroutine(
    prompt: Optional[str] = None,
    endpoint: Optional[str] = None,
    #download_image: bool = False,
    upload_image: bool = True,
    verbose: bool = True
) -> Dict[str, Any]:
    """
    使用自然语言或直接 endpoint 查询 STRING 蛋白互作数据库。
    支持 JSON/TSV/Image/SVG 输出，并上传图片返回 URL。
    """
    base_url = "https://version-12-0.string-db.org/api"

    if not prompt and not endpoint:
        return {"error": "Either a prompt or an endpoint must be provided"}

    description = ""
    if prompt:
        schema_path = os.path.join(os.path.dirname(__file__), "schema_db", "stringdb.pkl")
        with open(schema_path, "rb") as f:
            stringdb_schema = pickle.load(f)

        system_template = """
        你是蛋白互作专家，帮助将自然语言转换为 STRING API 请求。

        STRING API SCHEMA:
        {schema}

        输出仅 JSON，字段:
        1. full_url
        2. description
        3. output_format (json, tsv, image, svg)
        """
        claude_res = _query_claude_for_api(
            prompt=prompt,
            schema=stringdb_schema,
            system_template=system_template,

        )
        if not claude_res.get("success", False):
            return claude_res
        info = claude_res["data"]
        endpoint = info.get("full_url", "")
        description = info.get("description", "")
        output_format = info.get("output_format", "json")
        if not endpoint:
            return {"error": "Failed to generate endpoint", "claude_response": claude_res.get("raw_response")}
    else:
        if endpoint.startswith("/"):
            endpoint = f"{base_url}{endpoint}"
        elif not endpoint.startswith("http"):
            endpoint = f"{base_url}/{endpoint.lstrip('/')}"
        description = "Direct STRING API query"
        output_format = "json" if "json" in endpoint or "tsv" in endpoint else "image"

    # ⬇️ 上传图片而非本地保存
    if output_format in {"image", "svg"}:
        if upload_image:
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.get(endpoint) as resp:
                        resp.raise_for_status()
                        img_data = await resp.read()

                suffix = "svg" if "svg" in endpoint else "png"
                now = datetime.now().strftime("%Y%m%d_%H%M%S")
                file_name = f"string_image_{now}.{suffix}"

                file_url = await upload_content_to_minio(
                    content=img_data,
                    file_name=file_name,
                    file_extension=f".{suffix}",
                    content_type="image/svg+xml" if suffix == "svg" else "image/png",
                    no_expired=True,
                )
                return {
                    "success": True,
                    "query_info": {"endpoint": endpoint, "description": description},
                    "result": {"image_uploaded": True, "file_url": file_url}
                }
            except Exception as e:
                return {"success": False, "error": f"Image upload failed: {str(e)}", "query_info": {"endpoint": endpoint}}
        else:
            # 仅返回原始 URL
            return {
                "success": True,
                "query_info": {"endpoint": endpoint, "description": description},
                "result": {"image_available": True, "download_url": endpoint}
            }

    # ⬇️ 处理非图片格式
    api_res = _query_rest_api(endpoint=endpoint, method="GET", description=description)
    if not verbose and api_res.get("success") and "result" in api_res:
        return _format_query_results(api_res["result"])
    return api_res

# 注册 STRINGDB 工具
stringdb_tool = StructuredTool.from_function(
    coroutine=query_stringdb_coroutine,
    name=Tools.QUERY_STRINGDB,
   description="""
    【领域：生物】
    Query the STRING protein interaction database using natural language or direct endpoint.
    
    
    Returns:
    dict: Dictionary containing the query results or error information
    
    Examples:
    - Natural language: query_stringdb("Show protein interactions for BRCA1 and BRCA2 in humans")
    - Direct endpoint: query_stringdb(endpoint="https://string-db.org/api/json/network?identifiers=BRCA1,BRCA2&species=9606")
    """,
    args_schema=QuerySTRINGDBInput,
    metadata={"args_schema_json":QuerySTRINGDBInput.schema()}
)



# === 工具 14: Reactome 路径数据库查询工具===
# 测试成功
class QueryReactomeInput(BaseModel):
    """
    Reactome 路径数据库查询工具输入模型
    """
    prompt: Optional[str] = Field(
        None,
        description="自然语言查询，如: 'Find pathways related to DNA repair'"
    )
    # endpoint: Optional[str] = Field(
    #     None,
    #     description="直接 API 端点或完整 URL，如: 'data/pathways/R-HSA-73894'"
    # )
    download: bool = Field(
        False,
        description="是否下载通路示意图"
    )
    verbose: bool = Field(
        True,
        description="是否返回完整 API 响应；若 False 则仅返回格式化结果"
    )





async def query_reactome_coroutine(
    prompt: Optional[str] = None,
    upload_image: bool = True,
    verbose: bool = True
) -> Dict[str, Any]:
    """
    使用自然语言查询 Reactome 数据库。
    支持 JSON 数据输出，或上传通路示意图并返回其 URL。
    """
    if not prompt:
        return {"error": "必须提供自然语言提示 (A prompt must be provided)"}

    # 1. 使用 LLM 将自然语言 prompt 转换为 API 请求
    schema_path = os.path.join(os.path.dirname(__file__), "schema_db", "reactome.pkl")
    with open(schema_path, "rb") as f:
        reactome_schema = pickle.load(f)

    # 模仿 stringdb 的方式，让 LLM 直接生成完整的 URL 和输出格式
    system_template = """
    你是 Reactome API 专家，负责将自然语言查询转换为 Reactome API 的直接请求 URL。

    Reactome API SCHEMA:
    {schema}

    重要提示：
    1.  如果用户请求的是通路图或示意图 (diagram)，请直接生成图片的 URL。图片 URL 的格式通常是：
        `https://reactome.org/ContentService/data/pathway/STABLE_ID/diagram`
        你需要从用户的查询中识别出通路的稳定ID (stId)，例如 'R-HSA-1640170'。
    2.  对于其他数据查询，请生成相应的 JSON API URL。

    请严格按照以下 JSON 格式输出，不要包含任何其他文字或解释：
    {{
        "full_url": "...",
        "description": "对生成URL的简短描述",
        "output_format": "json 或 image"
    }}
    """
    claude_res =  _query_claude_for_api(
        prompt=prompt,
        schema=reactome_schema,
        system_template=system_template,
    )

    if not claude_res.get("success", False):
        return claude_res
        
    info = claude_res["data"]
    endpoint = info.get("full_url")
    description = info.get("description", "")
    output_format = info.get("output_format", "json")
    
    if not endpoint:
        return {"error": "无法从 prompt 生成有效的 API 请求", "claude_response": claude_res.get("raw_response")}

    # 2. 根据输出格式处理请求
    # ⬇️ 如果需要图片，则获取图片、上传并返回 URL
    if output_format == "image":
        if upload_image:
            try:
                # 使用 aiohttp 异步获取图片数据
                async with aiohttp.ClientSession() as session:
                    async with session.get(endpoint) as resp:
                        resp.raise_for_status()
                        img_data = await resp.read()

                # 上传到云存储 (例如 MinIO)
                suffix = "png"  # Reactome 通路图通常是 png 格式
                now = datetime.now().strftime("%Y%m%d_%H%M%S")
                file_name = f"reactome_diagram_{now}.{suffix}"

                file_url = await upload_content_to_minio(
                    content=img_data,
                    file_name=file_name,
                    file_extension=f".{suffix}",
                    content_type="image/png",
                    no_expired=True,
                )
                
                return {
                    "success": True,
                    "query_info": {"endpoint": endpoint, "description": description},
                    "result": {"image_uploaded": True, "file_url": file_url}
                }
            except Exception as e:
                return {"success": False, "error": f"图片处理或上传失败: {str(e)}", "query_info": {"endpoint": endpoint}}
        else:
            # 如果不上传，则直接返回图片的原始 URL
            return {
                "success": True,
                "query_info": {"endpoint": endpoint, "description": description},
                "result": {"image_available": True, "download_url": endpoint}
            }

    # ⬇️ 如果是 JSON 数据，则正常请求并返回结果
    # api_res =  _query_rest_api(endpoint=endpoint, method="GET", description=description)
    # if not verbose and api_res.get("success") and "result" in api_res:
    #     return _format_query_results(api_res["result"])
        
    # return api_res
    # ⬇️ 如果是 JSON 数据，则正常请求并返回结果
    api_res =  _query_rest_api(endpoint=endpoint, method="GET", description=description)

    if not verbose and api_res.get("success") and "result" in api_res:
        result = _format_query_results(api_res["result"])
    else:
        result = api_res

    # === 👇 加入 10000 字符限制处理 ===
    if isinstance(result, dict):
        text = json.dumps(result, ensure_ascii=False, indent=2)
    else:
        text = str(result)

    MAX_OUTPUT_LEN = 10000
    if len(text) > MAX_OUTPUT_LEN:
        text = (
            "The output is too long to be added to context.\n"
            f"Here are the first {MAX_OUTPUT_LEN // 1000}K characters...\n\n"
            + text[:MAX_OUTPUT_LEN]
        )

    return {
        "success": True,
        "query_info": {"endpoint": endpoint, "description": description},
        "result": text
    }



# 注册 Reactome 工具
reactome_tool = StructuredTool.from_function(
    coroutine=query_reactome_coroutine,
    name=Tools.QUERY_REACTOME,
   description="""
    【领域：生物】
  Query the Reactome database using natural language or a direct endpoint.
    注意：必须传入prompt！
    Returns:
    dict: Dictionary containing the query results or error information
    
    Examples:
    - Natural language: query_reactome("Find pathways related to DNA repair")
    - Direct endpoint: query_reactome(endpoint="data/pathways/R-HSA-73894")
    """,
    args_schema=QueryReactomeInput,
    metadata={"args_schema_json":QueryReactomeInput.schema()}
)

# === 工具 15: OpenTargets Genetics API 查询工具 ===
# 测试失败，api未响应
class QueryOpenTargetsGeneticsInput(BaseModel):
    """
    OpenTargets Genetics API 查询工具输入模型
    """
    prompt: Optional[str] = Field(
        None,
        description="自然语言查询，如: 'Get information about variant 1_154453788_C_T'"
    )
    query: Optional[str] = Field(
        None,
        description="GraphQL 查询字符串，若提供则跳过自然语言转换"
    )
    variables: Optional[Dict[str, Any]] = Field(
        None,
        description="GraphQL 查询变量，如: {'variantId': '1_154453788_C_T'}"
    )

    verbose: bool = Field(
        True,
        description="是否返回完整 API 响应；若 False 则仅返回格式化结果"
    )

def query_opentarget_genetics_coroutine(
    prompt: Optional[str] = None,
    query: Optional[str] = None,
    variables: Optional[Dict[str, Any]] = None,

    verbose: bool = True
) -> Dict[str, Any]:
    """
    使用自然语言或直接 GraphQL query 查询 OpenTargets Genetics API。
    """
    OPENTARGETS_URL = "https://api.genetics.opentargets.org/graphql"

    # 校验参数
    if not prompt and not query:
        return {"error": "Either a prompt or a GraphQL query must be provided"}

    # 自然语言 -> GraphQL
    if prompt and not query:
        schema_path = os.path.join(os.path.dirname(__file__), "schema_db", "opentarget_genetics.pkl")
        with open(schema_path, "rb") as f:
            ot_schema = pickle.load(f)

        system_template = """
        你是 OpenTargets Genetics GraphQL 专家，将自然语言请求转换为查询。

        SCHEMA:
        {schema}

        输出 JSON，字段:
        1. query: 完整 GraphQL 查询字符串
        2. variables: 查询变量对象
        """
        claude_res = _query_claude_for_api(
            prompt=prompt,
            schema=ot_schema,
            system_template=system_template,

        )
        if not claude_res.get("success", False):
            return claude_res

        data = claude_res["data"]
        query = data.get("query", "")
        if variables is None:
            variables = data.get("variables", {})
        if not query:
            return {"error": "Failed to generate GraphQL query", "claude_response": claude_res.get("raw_response")}

    # 执行 GraphQL 请求
    api_res = _query_rest_api(
        endpoint=OPENTARGETS_URL,
        method="POST",
        json_data={"query": query, "variables": variables or {}},
        headers={"Content-Type": "application/json"}
    )
    if not api_res.get("success", False):
        return api_res

    if not verbose and "result" in api_res:
        return _format_query_results(api_res["result"])
    return api_res

# 注册 OpenTargets Genetics 工具
opentargets_genetics_tool = StructuredTool.from_function(
    func=query_opentarget_genetics_coroutine,
    name=Tools.QUERY_OPENTARGETS_GENETICS,
   description="""
    【领域：生物】
    Query the OpenTargets Platform API using natural language or a direct GraphQL query.
    
    Returns:
    dict: Dictionary containing the query results or error information
    
    Examples:
    - Natural language: query_opentarget("Find drug targets for Alzheimer's disease")
    - Direct query: query_opentarget(query="query diseaseAssociations($diseaseId: String!) {...}", 
                                     variables={"diseaseId": "EFO_0000249"})
    """,
    args_schema=QueryOpenTargetsGeneticsInput,
    metadata={"args_schema_json":QueryOpenTargetsGeneticsInput.schema()}
)

# # === 工具 16: Ensembl REST API查询工具 ===
class QueryEnsemblInput(BaseModel):
    """
    Ensembl REST API 查询工具输入模型
    """
    prompt: Optional[str] = Field(
        None,
        description="自然语言查询，如: 'Get information about the human BRCA2 gene'"
    )
    endpoint: Optional[str] = Field(
        None,
        description="直接 API 端点（如 'lookup/symbol/homo_sapiens/BRCA2'）或完整 URL"
    )

    verbose: bool = Field(
        True,
        description="是否返回完整 API 响应；若 False 则仅返回格式化结果"
    )

def query_ensembl_coroutine(
    prompt: Optional[str] = None,
    endpoint: Optional[str] = None,
    verbose: bool = True
) -> Dict[str, Any]:
    """
    使用自然语言或直接 endpoint 查询 Ensembl REST API。
    """
    base_url = "https://rest.ensembl.org"
    # 参数校验
    if not prompt and not endpoint:
        return {"error": "Either a prompt or an endpoint must be provided"}

    # 自然语言 -> endpoint
    if prompt:
        schema_path = os.path.join(os.path.dirname(__file__), "schema_db", "ensembl.pkl")
        with open(schema_path, "rb") as f:
            ensembl_schema = pickle.load(f)

        system_template = """
        你是 Ensembl REST API 专家，将自然语言请求转换为合适的 API 端点和参数。

        SCHEMA:
        {schema}

        输出 JSON，字段:
        1. endpoint: 端点路径 (如 "lookup/symbol/homo_sapiens/BRCA2")
        2. params: 查询参数对象
        3. description: 查询说明
        """
        claude_res = _query_claude_for_api(
            prompt=prompt,
            schema=ensembl_schema,
            system_template=system_template,
        )
        if not claude_res.get("success", False):
            return claude_res

        info = claude_res["data"]
        endpoint = info.get("endpoint", "")
        params = info.get("params", {})
        description = info.get("description", "")
        if not endpoint:
            return {
                "error": "Failed to generate endpoint",
                "claude_response": claude_res.get("raw_response")
            }
    else:
        # 直接 endpoint
        if endpoint.startswith(base_url):
            endpoint = endpoint[len(base_url):].lstrip('/')
        params = {}
        description = "Direct query to Ensembl API"

    # 去除前导斜杠
    endpoint = endpoint.lstrip('/')
    url = f"{base_url}/{endpoint}"

    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json"
    }

    # 执行请求
    api_res = _query_rest_api(
        endpoint=url,
        method="GET",
        params=params,
        headers=headers,
        description=description
    )

    if not verbose and api_res.get("success") and "result" in api_res:
        return _format_query_results(api_res["result"])
    return api_res

# 注册 Ensembl 工具
ensembl_tool = StructuredTool.from_function(
    func=query_ensembl_coroutine,
    name='QUERY_ENSEMBL',
   description="""
   【领域：生物】
    Query the Ensembl REST API using natural language or a direct endpoint.
    
    Parameters:
    prompt (str, required): Natural language query about genomic data
    endpoint (str, optional): Direct API endpoint to query (e.g., "lookup/symbol/human/BRCA2") or full URL
    max_results (int): Maximum number of results to return
    verbose (bool): Whether to return detailed results
    
    Returns:
    dict: Dictionary containing the query results or error information
    
    Examples:
    - Natural language: query_ensembl("Get information about the human BRCA2 gene")
    - Direct endpoint: query_ensembl(endpoint="lookup/symbol/homo_sapiens/BRCA2")
    """,
    args_schema=QueryEnsemblInput
)

# === 工具 17: InterPro REST API 查询工具 ===

class QueryInterProInput(BaseModel):
    """
    InterPro REST API 查询工具输入模型
    """
    prompt: Optional[str] = Field(
        None,
        description="自然语言查询，如: 'Find information about kinase domains in InterPro'"
    )
    endpoint: Optional[str] = Field(
        None,
        description="直接端点路径或完整 URL，如: '/entry/interpro/IPR023411'"
    )

    max_results: int = Field(
        3,
        description="每页最大返回条目数"
    )

def query_interpro_coroutine(
    prompt: Optional[str] = None,
    endpoint: Optional[str] = None,
    max_results: int = 3
) -> Dict[str, Any]:
    """
    使用自然语言或直接 endpoint 查询 InterPro REST API。
    """
    base_url = "https://www.ebi.ac.uk/interpro/api"
    if not prompt and not endpoint:
        return {"error": "Either a prompt or an endpoint must be provided"}

    # 自然语言 -> 完整 URL
    if prompt:
        schema_path = os.path.join(os.path.dirname(__file__), "schema_db", "interpro.pkl")
        with open(schema_path, "rb") as f:
            interpro_schema = pickle.load(f)

        system_template = """
        你是蛋白域专家，将自然语言转换为 InterPro REST API 请求。

        SCHEMA:
        {schema}

        输出 JSON，字段:
        1. full_url: 完整请求 URL
        2. description: 查询说明
        """
        claude_res = _query_claude_for_api(
            prompt=prompt,
            schema=interpro_schema,
            system_template=system_template,
        )
        if not claude_res.get("success", False):
            return claude_res
        info = claude_res["data"]
        endpoint = info.get("full_url", "")
        description = info.get("description", "")
        if not endpoint:
            return {"error": "Failed to generate endpoint", "claude_response": claude_res.get("raw_response")}
    else:
        # 直接 endpoint -> 完整 URL
        if endpoint.startswith("/"):
            endpoint = f"{base_url}{endpoint}"
        elif not endpoint.startswith("http"):
            endpoint = f"{base_url}/{endpoint.lstrip('/')}"
        description = "Direct query to InterPro API"

    # 分页参数
    params = {"page": 1, "page_size": max_results}

    # 调用 REST API
    api_res = _query_rest_api(
        endpoint=endpoint,
        method="GET",
        params=params,
        description=description
    )
    return api_res

# 注册 InterPro 工具
query_interpro = StructuredTool.from_function(
    func=query_interpro_coroutine,
    name=Tools.QUERY_INTERPRO,
   description="""
    【领域：生物】
  Query the InterPro REST API using natural language or a direct endpoint.
    
    Returns:
    dict: Dictionary containing both the query information and the InterPro API results
    
    Examples:
    - Natural language: query_interpro("Find information about kinase domains in InterPro")
    - Direct endpoint: query_interpro(endpoint="/entry/interpro/IPR023411")
    """,
    args_schema=QueryInterProInput,
    metadata={"args_schema_json":QueryInterProInput.schema()}
)


# # === 工具 18: OpenTargets Platform GraphQL 查询工具 ===

# class QueryOpenTargetsInput(BaseModel):
#     """
#     OpenTargets Platform GraphQL 查询工具输入模型
#     """
#     prompt: Optional[str] = Field(
#         None,
#         description="自然语言查询，如: 'Find drug targets for Alzheimer's disease'"
#     )
#     query: Optional[str] = Field(
#         None,
#         description="GraphQL 查询字符串，若提供则跳过自然语言转换"
#     )
#     variables: Optional[Dict[str, Any]] = Field(
#         None,
#         description="GraphQL 查询变量，如: {'diseaseId': 'EFO_0000249'}"
#     )
#     verbose: bool = Field(
#         False,
#         description="是否返回完整 API 响应；若 False 则仅返回格式化结果"
#     )

# def query_opentarget_coroutine(
#     prompt: Optional[str] = None,
#     query: Optional[str] = None,
#     variables: Optional[Dict[str, Any]] = None,
#     verbose: bool = False
# ) -> Dict[str, Any]:
#     """
#     使用自然语言或直接 GraphQL query 查询 OpenTargets Platform API。
#     """
#     OPENTARGETS_URL = "https://api.platform.opentargets.org/api/v4/graphql"
#     # 参数校验
#     if not prompt and not query:
#         return {"error": "Either a prompt or a GraphQL query must be provided"}

#     # 自然语言 -> GraphQL
#     if prompt and not query:
#         schema_path = os.path.join(os.path.dirname(__file__), "schema_db", "opentarget.pkl")
#         with open(schema_path, "rb") as f:
#             ot_schema = pickle.load(f)

#         system_template = """
#         你是 OpenTargets Platform GraphQL 专家，将自然语言转换为查询。

#         SCHEMA:
#         {schema}

#         输出 JSON，字段:
#         1. query: 完整 GraphQL 查询字符串
#         2. variables: 查询变量对象
#         """
#         claude_res = _query_claude_for_api(
#             prompt=prompt,
#             schema=ot_schema,
#             system_template=system_template,
#         )
#         if not claude_res.get("success", False):
#             return claude_res
#         data = claude_res["data"]
#         query = data.get("query", "")
#         if variables is None:
#             variables = data.get("variables", {})
#         if not query:
#             return {"error": "Failed to generate GraphQL query", "claude_response": claude_res.get("raw_response")}

#     # 执行 GraphQL 请求
#     api_res = _query_rest_api(
#         endpoint=OPENTARGETS_URL,
#         method="POST",
#         json_data={"query": query, "variables": variables or {}},
#         headers={"Content-Type": "application/json"},
#         description="OpenTargets Platform GraphQL query"
#     )
#     if not api_res.get("success", False):
#         return api_res

#     if not verbose and "result" in api_res:
#         api_res["result"] = _format_query_results(api_res["result"])
#     return api_res

# # 注册 OpenTargets 工具
# opentarget_tool = StructuredTool.from_function(
#     func=query_opentarget_coroutine,
#     name=Tools.QUERY_OPENTARGET,
#    description="""
 #   【领域：生物】
#   Query the OpenTargets Platform API using natural language or a direct GraphQL query.
    
#     Parameters:
#     prompt (str, required): Natural language query about drug targets, diseases, and mechanisms
#     query (str, optional): Direct GraphQL query string
#     variables (dict, optional): Variables for the GraphQL query
#     verbose (bool): Whether to return detailed results
    
#     Returns:
#     dict: Dictionary containing the query results or error information
    
#     Examples:
#     - Natural language: query_opentarget("Find drug targets for Alzheimer's disease")
#     - Direct query: query_opentarget(query="query diseaseAssociations($diseaseId: String!) {...}", 
#                                      variables={"diseaseId": "EFO_0000249"})
#     """,
#     args_schema=QueryOpenTargetsInput
# )

# === 工具 19: GtoPdb 查询工具 ===


class QueryGtoPdbInput(BaseModel):
    """
    GtoPdb 查询工具输入模型
    """
    prompt: Optional[str] = Field(
        None,
        description="自然语言查询，如: 'Find ligands that target the beta-2 adrenergic receptor'"
    )
    endpoint: Optional[str] = Field(
        None,
        description="完整或相对 API 端点，如: 'targets?type=GPCR&name=beta-2'"
    )
    verbose: bool = Field(
        True,
        description="是否返回完整响应；若 False 则仅返回格式化结果"
    )

def query_gtopdb_coroutine(
    prompt: Optional[str] = None,
    endpoint: Optional[str] = None,
    verbose: bool = True
) -> Dict[str, Any]:
    """
    使用自然语言或直接 endpoint 查询 GtoPdb（Guide to PHARMACOLOGY）。
    """
    base_url = "https://www.guidetopharmacology.org/services"
    if not prompt and not endpoint:
        return {"error": "Either a prompt or an endpoint must be provided"}

    # 自然语言 -> endpoint
    if prompt:
        schema_path = os.path.join(os.path.dirname(__file__), "schema_db", "gtopdb.pkl")
        with open(schema_path, "rb") as f:
            gtopdb_schema = pickle.load(f)

        system_template = """
        你是药理学专家，将自然语言请求转换为 GtoPdb API 请求。

        SCHEMA:
        {schema}

        输出 JSON，字段:
        1. endpoint: 完整请求端点
        2. description: 查询说明
        """
        claude_res = _query_claude_for_api(
            prompt=prompt,
            schema=gtopdb_schema,
            system_template=system_template,
        )
        if not claude_res.get("success", False):
            return claude_res
        info = claude_res["data"]
        endpoint = info.get("endpoint", "")
        description = info.get("description", "")
        if not endpoint:
            return {"error": "Failed to generate endpoint", "claude_response": claude_res.get("raw_response")}
    else:
        description = f"Direct query to GtoPdb endpoint: {endpoint}"

    # 构造完整 URL
    if endpoint.startswith("/"):
        url = f"{base_url}{endpoint}"
    elif endpoint.startswith("http"):
        url = endpoint
    else:
        url = f"{base_url}/{endpoint.lstrip('/')}"

    # 执行请求
    api_res = _query_rest_api(
        endpoint=url,
        method="GET",
        description=description
    )

    # 非 verbose 时格式化结果
    if not verbose and api_res.get("success") and "result" in api_res:
        api_res["result"] = _format_query_results(api_res["result"])
    return api_res

# 注册 GtoPdb 工具
gtopdb_tool = StructuredTool.from_function(
    func=query_gtopdb_coroutine,
    name='QUERY_GTOPDB',
   description="""
   【领域：生物】
    查询 GtoPdb（Guide to PHARMACOLOGY）数据库。支持自然语言或 endpoint 调用，
    返回原始或格式化结果。参数：prompt, endpoint, verbose。
    """,
    args_schema=QueryGtoPdbInput
)
