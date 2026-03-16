
import json
import pickle
import time
from typing import Dict, Optional, Any

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field
from langchain_openai import ChatOpenAI
from langchain_deepseek import ChatDeepSeek
import hashlib

from dotenv import load_dotenv
import httpx
import aiohttp
import requests
import asyncio
import os
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import InjectedToolArg
from pydantic import BaseModel, Field
from typing_extensions import Annotated

from workflow import config as science_config


# ============================================================================
# Helper Functions (to be imported or implemented separately)
# ============================================================================

# These functions should be imported from your existing codebase:
# - _query_claude_for_api
# - _query_rest_api
# - _query_ncbi_database
# - _format_query_results


DEEPSEEK_CHAT = ChatDeepSeek(
        model=science_config.DeepSeekV3_2.model,
        base_url=science_config.DeepSeekV3_2.base_url,
        api_key=science_config.DeepSeekV3_2.api_key,
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






# ============================================================================
# Input Schema Models
# ============================================================================

class QueryDbSNPInput(BaseModel):
    """
    Input parameters for querying the NCBI dbSNP database
    """
    prompt: Optional[str] = Field(None, description="Natural language query about genetic variants/SNPs (e.g., 'Find pathogenic variants in BRCA1')")
    search_term: Optional[str] = Field(None, description="Direct search term using dbSNP syntax (e.g., 'BRCA1[Gene Name] AND pathogenic[Clinical Significance]')")
    max_results: int = Field(3, description="Maximum number of results to return")


class QueryEnsemblInput(BaseModel):
    """
    Input parameters for querying the Ensembl REST API
    """
    prompt: Optional[str] = Field(None, description="Natural language query about genomic data (e.g., 'Get information about the human BRCA2 gene')")
    endpoint: Optional[str] = Field(None, description="Direct API endpoint path (e.g., 'lookup/symbol/homo_sapiens/BRCA2') or full URL")
    verbose: bool = Field(True, description="Whether to return detailed results or formatted summary")


class QueryOpenTargetInput(BaseModel):
    """
    Input parameters for querying the OpenTargets Platform API
    """
    prompt: Optional[str] = Field(None, description="Natural language query about drug targets, diseases, and mechanisms (e.g., 'Find drug targets for Alzheimer's disease')")
    query: Optional[str] = Field(None, description="Direct GraphQL query string")
    variables: Optional[Dict] = Field(None, description="Variables for the GraphQL query as a dictionary")
    verbose: bool = Field(False, description="Whether to return detailed results or formatted summary")


class QueryGWASCatalogInput(BaseModel):
    """
    Input parameters for querying the GWAS Catalog API
    """
    prompt: Optional[str] = Field(None, description="Natural language query about GWAS data (e.g., 'Find GWAS studies related to Type 2 diabetes')")
    endpoint: Optional[str] = Field(None, description="Full API endpoint URL or relative path (e.g., 'studies' or full URL)")
    max_results: int = Field(3, description="Maximum number of results to return")


class QueryUniProtInput(BaseModel):
    """
    Input parameters for querying the UniProt REST API
    """
    prompt: Optional[str] = Field(None, description="Natural language query about proteins (e.g., 'Find information about human insulin protein')")
    endpoint: Optional[str] = Field(None, description="UniProt API endpoint URL, can be full or relative path")
    max_results: int = Field(5, description="Maximum number of results to return")


class AdvancedWebSearchInput(BaseModel):
    """
    Input parameters for advanced web search using Claude
    """
    query: str = Field(..., description="The search phrase for Claude to look up. Craft carefully to find the most relevant information.")
    max_searches: int = Field(1, description="Upper bound on the number of searches Claude may issue inside this request")
    max_retries: int = Field(3, description="Maximum number of retry attempts with exponential backoff")


class QueryArxivInput(BaseModel):
    """
    Input parameters for querying arXiv
    """
    query: str = Field(..., description="The search query string for arXiv papers (e.g., 'quantum computing machine learning')")
    max_papers: int = Field(10, description="Maximum number of papers to retrieve")


class QueryScholarInput(BaseModel):
    """
    Input parameters for querying Google Scholar
    """
    query: str = Field(..., description="The search query string for Google Scholar (e.g., 'deep learning image recognition')")


class QueryPubMedInput(BaseModel):
    """
    Input parameters for querying PubMed
    """
    query: str = Field(..., description="The search query string for PubMed papers (e.g., 'cancer immunotherapy')")
    max_papers: int = Field(10, description="Maximum number of papers to retrieve")
    max_retries: int = Field(3, description="Maximum number of retry attempts with modified queries")


class SearchGoogleInput(BaseModel):
    """
    Input parameters for Google search
    """
    query: str = Field(..., description="The search query string (e.g., 'protocol text or search question')")
    num_results: int = Field(3, description="Number of results to return")
    language: str = Field("en", description="Language code for search results (default: 'en')")


# ============================================================================
# Tool Functions
# ============================================================================

def query_dbsnp(
    prompt=None,
    search_term=None,
    max_results=3,
):
    """Query the NCBI dbSNP database using natural language or a direct search term.

    Parameters
    ----------
    prompt (str, optional): Natural language query about genetic variants/SNPs
    search_term (str, optional): Direct search term in dbSNP syntax
    max_results (int): Maximum number of results to return

    Returns
    -------
    dict: Dictionary containing the query results or error information

    Examples
    --------
    - Natural language: query_dbsnp(prompt="Find pathogenic variants in BRCA1")
    - Direct search: query_dbsnp(search_term="BRCA1[Gene Name] AND pathogenic[Clinical Significance]")
    """
    if not prompt and not search_term:
        return {"error": "Either a prompt or a search term must be provided"}

    if prompt:
        # Load dbSNP schema
        schema_path = os.path.join(os.path.dirname(__file__), "schema_db", "dbsnp.pkl")
        with open(schema_path, "rb") as f:
            dbsnp_schema = pickle.load(f)

        # Create system prompt template
        system_template = """
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

        # Query Claude to generate the API call
        claude_result = _query_claude_for_api(
            prompt=prompt,
            schema=dbsnp_schema,
            system_template=system_template,
        )

        if not claude_result["success"]:
            return claude_result

        # Get the search term from Claude's response
        query_info = claude_result["data"]
        search_term = query_info.get("search_term", "")

        if not search_term:
            return {
                "error": "Failed to generate a valid search term from the prompt",
                "claude_response": claude_result.get("raw_response", "No response"),
            }

    # Execute the dbSNP query using the helper function
    result = _query_ncbi_database(
        database="snp",
        search_term=search_term,
        max_results=max_results,
    )

    return result


def query_ensembl(
    prompt=None,
    endpoint=None,
    verbose=True,
):
    """Query the Ensembl REST API using natural language or a direct endpoint.

    Parameters
    ----------
    prompt (str, optional): Natural language query about genomic data
    endpoint (str, optional): Direct API endpoint to query (e.g., "lookup/symbol/human/BRCA2") or full URL
    verbose (bool): Whether to return detailed results

    Returns
    -------
    dict: Dictionary containing the query results or error information

    Examples
    --------
    - Natural language: query_ensembl(prompt="Get information about the human BRCA2 gene")
    - Direct endpoint: query_ensembl(endpoint="lookup/symbol/homo_sapiens/BRCA2")
    """
    # Base URL for Ensembl API
    base_url = "https://rest.ensembl.org"

    # Ensure we have either a prompt or an endpoint
    if not prompt and not endpoint:
        return {"error": "Either a prompt or an endpoint must be provided"}

    # If using prompt, parse with Claude
    if prompt:
        # Load Ensembl schema
        schema_path = os.path.join(os.path.dirname(__file__), "schema_db", "ensembl.pkl")
        with open(schema_path, "rb") as f:
            ensembl_schema = pickle.load(f)

        # Create system prompt template
        system_template = """
        You are a genomics and bioinformatics expert specialized in using the Ensembl REST API.

        Based on the user's natural language request, determine the appropriate Ensembl REST API endpoint and parameters.

        ENSEMBL REST API SCHEMA:
        {schema}

        Your response should be a JSON object with the following fields:
        1. "endpoint": The API endpoint to query (e.g., "lookup/symbol/homo_sapiens/BRCA2")
        2. "params": An object containing query parameters specific to the endpoint
        3. "description": A brief description of what the query is doing

        SPECIAL NOTES:
        - Chromosome region queries have a maximum length of 4900000 bp inclusive, so bp of start and end should be 4900000 bp apart. If the user's query exceeds this limit, Ensembl will return an error.
        - For symbol lookups, the format is "lookup/symbol/[species]/[symbol]"
        - To find the coordinates of a band on a chromosome, use /info/assembly/homo_sapiens/[chromosome] with parameters "band":1
        - To find the overlapping genes of a genomic region, use /overlap/region/homo_sapiens/[chromosome]:[start]-[end]
        - For sequence queries, specify the sequence type in parameters (genomic, cdna, cds, protein)
        - For converting rsID to hg38 genomic coordinates, use the "GET id/variation/[species]/[rsid]" endpoint
        - Many endpoints support "content-type" parameter for format specification (application/json, text/xml)

        Return ONLY the JSON object with no additional text.
        """

        # Query Claude to generate the API call
        claude_result = _query_claude_for_api(
            prompt=prompt,
            schema=ensembl_schema,
            system_template=system_template,
        )

        if not claude_result["success"]:
            return claude_result

        # Get the endpoint and parameters from Claude's response
        query_info = claude_result["data"]
        endpoint = query_info.get("endpoint", "")
        params = query_info.get("params", {})
        description = query_info.get("description", "")

        if not endpoint:
            return {
                "error": "Failed to generate a valid endpoint from the prompt",
                "claude_response": claude_result.get("raw_response", "No response"),
            }
    else:
        # Process provided endpoint
        if endpoint.startswith("http"):
            # If a full URL is provided, extract the endpoint part
            if endpoint.startswith(base_url):
                endpoint = endpoint[len(base_url):].lstrip("/")

        params = {}
        description = "Direct query to Ensembl API"

    # Remove leading slash if present
    if endpoint.startswith("/"):
        endpoint = endpoint[1:]

    # Prepare headers for JSON response
    headers = {"Content-Type": "application/json", "Accept": "application/json"}

    # Construct the URL
    url = f"{base_url}/{endpoint}"

    # Execute the Ensembl API request using the helper function
# 执行 API 请求
    api_result = _query_rest_api(
        endpoint=url,
        method="GET",
        params=params,
        headers=headers,
        description=description,
    )

    # --- 强力精简逻辑开始 ---
    # 如果不是 verbose 模式，且请求成功
    if not verbose and api_result.get("success"):
        data = api_result.get("result")
        
        if isinstance(data, dict):
            # 1. 提取基因层级的核心信息
            simplified = {
                "gene_id": data.get("id"),
                "symbol": data.get("display_name"),
                "description": data.get("description"),
                "chrom_region": f"{data.get('seq_region_name')}:{data.get('start')}-{data.get('end')}",
                "biotype": data.get("biotype")
            }

            # 2. 处理转录本（Transcripts），只保留身份 ID，彻底丢弃 Exon 坐标
            if "Transcript" in data:
                transcripts = data["Transcript"]
                simplified["total_transcripts"] = len(transcripts)
                # 仅展示前 3 个转录本作为示例
                simplified["transcripts_sample"] = [
                    {
                        "transcript_id": t.get("id"),
                        "biotype": t.get("biotype"),
                        "display_name": t.get("display_name")
                    } for t in transcripts[:3]
                ]
            
            # 用精简后的数据覆盖原结果
            api_result["result"] = simplified

    return api_result



def query_opentarget(
    prompt=None,
    query=None,
    variables=None,
    verbose=False,
):
    """Query the OpenTargets Platform API using natural language or a direct GraphQL query.

    Parameters
    ----------
    prompt (str, optional): Natural language query about drug targets, diseases, and mechanisms
    query (str, optional): Direct GraphQL query string
    variables (dict, optional): Variables for the GraphQL query
    verbose (bool): Whether to return detailed results

    Returns
    -------
    dict: Dictionary containing the query results or error information

    Examples
    --------
    - Natural language: query_opentarget(prompt="Find drug targets for Alzheimer's disease")
    - Direct query: query_opentarget(query="query diseaseAssociations($diseaseId: String!) {...}",
                                     variables={"diseaseId": "EFO_0000249"})
    """
    # Constants and initialization
    OPENTARGETS_URL = "https://api.platform.opentargets.org/api/v4/graphql"

    # Ensure we have either a prompt or a query
    if prompt is None and query is None:
        return {"error": "Either a prompt or a GraphQL query must be provided"}

    # If using prompt, parse with Claude
    if prompt:
        # Load OpenTargets schema
        schema_path = os.path.join(os.path.dirname(__file__), "schema_db", "opentarget.pkl")
        with open(schema_path, "rb") as f:
            opentarget_schema = pickle.load(f)

        # Create system prompt template
        system_template = """
        You are an expert in translating natural language requests into GraphQL queries for the OpenTargets Platform API.

        Here is a schema of the main types and queries available in the OpenTargets Platform API:
        {schema}

        Translate the user's natural language request into a valid GraphQL query for this API.
        Return only a JSON object with two fields:
        1. "query": The complete GraphQL query string
        2. "variables": A JSON object containing the variables needed for the query

        SPECIAL NOTES:
        - Disease IDs typically use EFO ontology (e.g., "EFO_0000249" for Alzheimer's disease)
        - Target IDs typically use Ensembl IDs (e.g., "ENSG00000197386" for ENSG00000197386)
        - The API can provide information about drug-target associations, disease-target associations, etc.
        - Always limit results to a reasonable number using "first" parameter (e.g., first: 10)
        - Always escape special characters, including quotes, in the query string (eg. \\" instead of ")

        Return ONLY the JSON object with no additional text or explanations.
        """

        # Query Claude to generate the API call
        claude_result = _query_claude_for_api(
            prompt=prompt,
            schema=opentarget_schema,
            system_template=system_template,
        )

        if not claude_result["success"]:
            return claude_result

        # Get the query and variables from Claude's response
        query_info = claude_result["data"]
        query = query_info.get("query", "")
        if variables is None:  # Only use Claude's variables if none provided
            variables = query_info.get("variables", {})

        if not query:
            return {
                "error": "Failed to generate a valid GraphQL query from the prompt",
                "claude_response": claude_result.get("raw_response", "No response"),
            }

    # Execute the GraphQL query
    api_result = _query_rest_api(
        endpoint=OPENTARGETS_URL,
        method="POST",
        json_data={"query": query, "variables": variables or {}},
        headers={"Content-Type": "application/json"},
        description="OpenTargets Platform GraphQL query",
    )

    # Format the results if not verbose and successful
    if not verbose and "success" in api_result and api_result["success"] and "result" in api_result:
        api_result["result"] = _format_query_results(api_result["result"])

    return api_result


def query_gwas_catalog(
    prompt=None,
    endpoint=None,
    max_results=3,
):
    """Query the GWAS Catalog API using natural language or a direct endpoint.

    Parameters
    ----------
    prompt (str, optional): Natural language query about GWAS data
    endpoint (str, optional): Full API endpoint to query (e.g., "https://www.ebi.ac.uk/gwas/rest/api/studies?diseaseTraitId=EFO_0001360")
    max_results (int): Maximum number of results to return

    Returns
    -------
    dict: Dictionary containing the query results or error information

    Examples
    --------
    - Natural language: query_gwas_catalog(prompt="Find GWAS studies related to Type 2 diabetes")
    - Direct endpoint: query_gwas_catalog(endpoint="studies")
    """
    # Base URL for GWAS Catalog API
    base_url = "https://www.ebi.ac.uk/gwas/rest/api"

    # Ensure we have either a prompt or an endpoint
    if prompt is None and endpoint is None:
        return {"error": "Either a prompt or an endpoint must be provided"}

    # If using prompt, parse with Claude
    if prompt:
        # Load GWAS Catalog schema
        schema_path = os.path.join(os.path.dirname(__file__), "schema_db", "gwas_catalog.pkl")
        with open(schema_path, "rb") as f:
            gwas_schema = pickle.load(f)

        # Create system prompt template
        system_template = """
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

        # Query Claude to generate the API call
        claude_result = _query_claude_for_api(
            prompt=prompt,
            schema=gwas_schema,
            system_template=system_template,
        )

        if not claude_result["success"]:
            return claude_result

        # Get the endpoint and parameters from Claude's response
        query_info = claude_result["data"]
        endpoint = query_info.get("endpoint", "")
        params = query_info.get("params", {})
        description = query_info.get("description", "")

        if not endpoint:
            return {
                "error": "Failed to generate a valid endpoint from the prompt",
                "claude_response": claude_result.get("raw_response", "No response"),
            }
    else:
        if endpoint is None:
            endpoint = ""  # Use root endpoint
        params = {"size": max_results}
        description = f"Direct query to {endpoint}"

    # Remove leading slash if present
    if endpoint.startswith("/"):
        endpoint = endpoint[1:]

    # Construct the URL
    url = f"{base_url}/{endpoint}"

    # Execute the GWAS Catalog API request using the helper function
    api_result = _query_rest_api(endpoint=url, method="GET", params=params, description=description)

    return api_result


def query_uniprot_database(
    prompt=None,
    endpoint=None,
    max_results=5,
):
    """Query the UniProt REST API using either natural language or a direct endpoint.

    Parameters
    ----------
    prompt (str, optional): Natural language query about proteins (e.g., "Find information about human insulin")
    endpoint (str, optional): Full or partial UniProt API endpoint URL to query directly
    max_results (int): Maximum number of results to return

    Returns
    -------
    dict: Dictionary containing the query information and the UniProt API results

    Examples
    --------
    - Natural language: query_uniprot_database(prompt="Find information about human insulin protein")
    - Direct endpoint: query_uniprot_database(endpoint="https://rest.uniprot.org/uniprotkb/P01308")
    """
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
    
    # Extract key information
    try:
        raw = api_result.get("result", {})
        # Get list based on interface type
        if isinstance(raw.get("results"), list):
            entries = raw["results"]
        else:
            # For /uniprotkb/{accession} returning object directly
            entries = [raw]
        
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


# def advanced_web_search_claude(
#     query: str,
#     max_searches: int = 1,
#     max_retries: int = 3,
# ) -> str:
#     """
#     Initiate an advanced web search by launching a specialized agent to collect relevant information 
#     and citations through multiple rounds of web searches for a given query.

#     Parameters
#     ----------
#     query : str
#         The search phrase you want Claude to look up. Craft the query carefully for the search agent.
#     max_searches : int, optional
#         Upper-bound on searches Claude may issue inside this request.
#     max_retries : int, optional
#         Maximum number of retry attempts with exponential backoff.

#     Returns
#     -------
#     str
#         A formatted string containing the full text response from Claude and the citations.

#     Examples
#     --------
#     - advanced_web_search_claude(query="Latest breakthroughs in CRISPR gene editing", max_searches=2)
#     """
#     import random
#     import anthropic

#     try:
#         from biomni.config import default_config
#         model = default_config.llm
#         api_key = default_config.api_key
#         if not api_key:
#             api_key = os.getenv("ANTHROPIC_API_KEY")
#     except ImportError:
#         model = "claude-4-sonnet-latest"
#         api_key = os.getenv("ANTHROPIC_API_KEY")

#     if "claude" not in model:
#         raise ValueError("Model must be a Claude model.")

#     if not api_key:
#         raise ValueError("Set your api_key explicitly.")

#     client = anthropic.Anthropic(api_key=api_key)
#     tool_def = {
#         "type": "web_search_20250305",
#         "name": "web_search",
#         "max_uses": max_searches,
#     }

#     delay = random.randint(1, 10)

#     for attempt in range(1, max_retries + 1):
#         try:
#             response = client.messages.create(
#                 model=model,
#                 max_tokens=4096,
#                 messages=[{"role": "user", "content": query}],
#                 tools=[tool_def],
#             )

#             paragraphs, citations = [], []
#             response.content = response.content
#             formatted_response = ""
#             for blk in response.content:
#                 if blk.type == "text":
#                     paragraphs.append(blk.text)
#                     formatted_response += blk.text

#                     if blk.citations:
#                         for cite in blk.citations:
#                             citations.append({"url": cite.url, "title": cite.title, "cited_text": cite.cited_text})
#                             formatted_response += f"(Citation: {cite.title} - {cite.url})"
#             return formatted_response

#         except Exception as e:
#             if attempt < max_retries:
#                 time.sleep(delay)
#                 delay *= 2
#                 continue
#             print(f"Error performing web search after {max_retries} attempts: {str(e)}")
#             return f"Error performing web search after {max_retries} attempts: {str(e)}"


def query_arxiv(query: str, max_papers: int = 10) -> str:
    """Query arXiv for papers based on the provided search query.

    Parameters
    ----------
    query (str): The search query string
    max_papers (int): The maximum number of papers to retrieve (default: 10)

    Returns
    -------
    str: The formatted search results or an error message

    Examples
    --------
    - query_arxiv(query="quantum computing machine learning", max_papers=5)
    """
    import arxiv

    try:
        client = arxiv.Client()
        search = arxiv.Search(query=query, max_results=max_papers, sort_by=arxiv.SortCriterion.Relevance)
        results = "\n\n".join([f"Title: {paper.title}\nSummary: {paper.summary}" for paper in client.results(search)])
        return results if results else "No papers found on arXiv."
    except Exception as e:
        return f"Error querying arXiv: {e}"


def query_scholar(query: str) -> str:
    """Query Google Scholar for papers based on the provided search query.

    Parameters
    ----------
    query (str): The search query string

    Returns
    -------
    str: The first search result formatted or an error message

    Examples
    --------
    - query_scholar(query="deep learning image recognition")
    """
    from scholarly import ProxyGenerator, scholarly

    # Set up a ProxyGenerator object to use free proxies
    # This needs to be done only once per session
    pg = ProxyGenerator()
    pg.FreeProxies()
    scholarly.use_proxy(pg)
    try:
        search_query = scholarly.search_pubs(query)
        result = next(search_query, None)
        if result:
            return f"Title: {result['bib']['title']}\nYear: {result['bib']['pub_year']}\nVenue: {result['bib']['venue']}\nAbstract: {result['bib']['abstract']}"
        else:
            return "No results found on Google Scholar."
    except Exception as e:
        return f"Error querying Google Scholar: {e}"


def query_pubmed(query: str, max_papers: int = 10, max_retries: int = 3) -> str:
    """Query PubMed for papers based on the provided search query.

    Parameters
    ----------
    query (str): The search query string
    max_papers (int): The maximum number of papers to retrieve (default: 10)
    max_retries (int): Maximum number of retry attempts with modified queries (default: 3)

    Returns
    -------
    str: The formatted search results or an error message

    Examples
    --------
    - query_pubmed(query="cancer immunotherapy", max_papers=5)
    """
    from pymed import PubMed

    try:
        pubmed = PubMed(tool="MyTool", email="your-email@example.com")  # Update with a valid email address

        # Initial attempt
        papers = list(pubmed.query(query, max_results=max_papers))

        # Retry with modified queries if no results
        retries = 0
        while not papers and retries < max_retries:
            retries += 1
            # Simplify query with each retry by removing the last word
            simplified_query = " ".join(query.split()[:-retries]) if len(query.split()) > retries else query
            time.sleep(1)  # Add delay between requests
            papers = list(pubmed.query(simplified_query, max_results=max_papers))

        if papers:
            results = "\n\n".join(
                [f"Title: {paper.title}\nAbstract: {paper.abstract}\nJournal: {paper.journal}" for paper in papers]
            )
            return results
        else:
            return "No papers found on PubMed after multiple query attempts."
    except Exception as e:
        return f"Error querying PubMed: {e}"


def search_google(query: str, num_results: int = 3, language: str = "en") -> str:
    """Search using Google search.

    Parameters
    ----------
    query (str): The search query (e.g., "protocol text or search question")
    num_results (int): Number of results to return (default: 3)
    language (str): Language code for search results (default: 'en')

    Returns
    -------
    str: String containing formatted search results with title, URL, and description

    Examples
    --------
    - search_google(query="CRISPR delivery methods", num_results=5)
    """
    from googlesearch import search
    
    try:
        results_string = ""
        search_query = f"{query}"

        print(f"Searching for {search_query} with {num_results} results and {language} language")

        for res in search(search_query, num_results=num_results, lang=language, advanced=True):
            print(f"Found result: {res.title}")
            title = res.title
            url = res.url
            description = res.description

            results_string += f"Title: {title}\nURL: {url}\nDescription: {description}\n\n"

    except Exception as e:
        print(f"Error performing search: {str(e)}")
        return f"Error performing search: {str(e)}"
    
    return results_string


# ============================================================================
# Tool Definitions
# ============================================================================

# Note: These tool names should be defined in your Tools enum/class
# For now, using descriptive strings

query_dbsnp_tool = StructuredTool.from_function(
    func=query_dbsnp,
    name="query_dbsnp",
    description="""
    【Domain: Biology/Genetics】
    Query the NCBI dbSNP database using either natural language or direct dbSNP search syntax.
    
    Returns:
    dict: Dictionary containing query information and dbSNP search results
    
    Examples:
    - Natural language: query_dbsnp(prompt="Find pathogenic variants in BRCA1")
    - Direct search: query_dbsnp(search_term="BRCA1[Gene Name] AND pathogenic[Clinical Significance]")
""",
    args_schema=QueryDbSNPInput,
    metadata={"args_schema_json": QueryDbSNPInput.schema()}
)

query_ensembl_tool = StructuredTool.from_function(
    func=query_ensembl,
    name="query_ensembl",
    description="""
    【Domain: Biology/Genomics】
    Query the Ensembl REST API using natural language or a direct endpoint path.
    
    Returns:
    dict: Dictionary containing query information and Ensembl API results
    
    Examples:
    - Natural language: query_ensembl(prompt="Get information about the human BRCA2 gene")
    - Direct endpoint: query_ensembl(endpoint="lookup/symbol/homo_sapiens/BRCA2")
""",
    args_schema=QueryEnsemblInput,
    metadata={"args_schema_json": QueryEnsemblInput.schema()}
)

query_opentarget_tool = StructuredTool.from_function(
    func=query_opentarget,
    name="query_opentarget",
    description="""
    【Domain: Biology/Drug Discovery】
    Query the OpenTargets Platform API using natural language or a direct GraphQL query.
    
    Returns:
    dict: Dictionary containing query information and OpenTargets API results
    
    Examples:
    - Natural language: query_opentarget(prompt="Find drug targets for Alzheimer's disease")
    - Direct query: query_opentarget(query="...", variables={"diseaseId": "EFO_0000249"})
""",
    args_schema=QueryOpenTargetInput,
    metadata={"args_schema_json": QueryOpenTargetInput.schema()}
)

query_gwas_catalog_tool = StructuredTool.from_function(
    func=query_gwas_catalog,
    name="query_gwas_catalog",
    description="""
    【Domain: Biology/Genetics】
    Query the GWAS Catalog API using natural language or a direct endpoint.
    
    Returns:
    dict: Dictionary containing query information and GWAS Catalog results
    
    Examples:
    - Natural language: query_gwas_catalog(prompt="Find GWAS studies related to Type 2 diabetes")

""",
    args_schema=QueryGWASCatalogInput,
    metadata={"args_schema_json": QueryGWASCatalogInput.schema()}
)

query_uniprot_tool = StructuredTool.from_function(
    func=query_uniprot_database,
    name="query_uniprot",
    description="""
    【Domain: Biology/Proteomics】
    Query the UniProt REST API using either natural language or a direct endpoint.
    
    Returns:
    dict: Dictionary containing the query information and the UniProt API results
    
    Examples:
    - Natural language: query_uniprot(prompt="Find information about human insulin protein")
    - Direct endpoint: query_uniprot(endpoint="https://rest.uniprot.org/uniprotkb/P01308")
""",
    args_schema=QueryUniProtInput,
    metadata={"args_schema_json": QueryUniProtInput.schema()}
)

# advanced_web_search_tool = StructuredTool.from_function(
#     func=advanced_web_search_claude,
#     name="advanced_web_search",
#     description="""
#     【Domain: General/Web Search】
#     Launch a specialized Claude agent to perform advanced web search with multiple rounds of searches.
    
#     Returns:
#     str: Formatted string containing Claude's response with relevant information and citations
    
#     Examples:
#     - advanced_web_search(query="Latest breakthroughs in CRISPR gene editing", max_searches=2)
# """,
#     args_schema=AdvancedWebSearchInput,
#     metadata={"args_schema_json": AdvancedWebSearchInput.schema()}
# )

query_arxiv_bio_tool = StructuredTool.from_function(
    func=query_arxiv,
    name="query_arxiv",
    description="""
    【Domain: Research/Literature】
    Query arXiv for academic papers based on the provided search query.
    
    Returns:
    str: Formatted string containing paper titles and summaries or an error message
    
    Examples:
    - query_arxiv(query="quantum computing machine learning", max_papers=5)
""",
    args_schema=QueryArxivInput,
    metadata={"args_schema_json": QueryArxivInput.schema()}
)

query_scholar_bio_tool = StructuredTool.from_function(
    func=query_scholar,
    name="query_scholar",
    description="""
    【Domain: Research/Literature】
    Query Google Scholar for academic papers based on the provided search query.
    
    Returns:
    str: Formatted string containing the first search result or an error message
    
    Examples:
    - query_scholar(query="deep learning image recognition")
""",
    args_schema=QueryScholarInput,
    metadata={"args_schema_json": QueryScholarInput.schema()}
)

query_pubmed_bio_tool = StructuredTool.from_function(
    func=query_pubmed,
    name="query_pubmed",
    description="""
    【Domain: Biology/Medicine】
    Query PubMed for biomedical papers based on the provided search query.
    
    Returns:
    str: Formatted string containing paper titles, abstracts, and journals or an error message
    
    Examples:
    - query_pubmed(query="cancer immunotherapy", max_papers=5)
""",
    args_schema=QueryPubMedInput,
    metadata={"args_schema_json": QueryPubMedInput.schema()}
)

search_google_tool = StructuredTool.from_function(
    func=search_google,
    name="search_google",
    description="""
    【Domain: General/Web Search】
    Perform a Google web search and return formatted results with titles, URLs, and descriptions.
    
    Returns:
    str: Formatted string containing search results or an error message
    
    Examples:
    - search_google(query="CRISPR delivery methods", num_results=5)
""",
    args_schema=SearchGoogleInput,
    metadata={"args_schema_json": SearchGoogleInput.schema()}
)



def _make_search_cache_key(query, start_date, end_date, site, gl, hl):
    key_dict = {
        "query": query,
        "start_date": start_date,
        "end_date": end_date,
        "site": site,
        "gl": gl,
        "hl": hl,
    }
    key_str = json.dumps(key_dict, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(key_str.encode("utf-8")).hexdigest()

# def _load_search_cache():
#     if os.path.exists(search_cache_path):
#         try:
#             with open(search_cache_path, "r", encoding="utf-8") as f:
#                 return json.load(f)
#         except Exception:
#             return {}
#     return {}


# 当前用的jina search 或 tavily
def _filter_serper_search_result(result_content: str) -> str:
    """Filter the search result to only include the relevant information."""
    try:
        data = json.loads(result_content)
        snippets = []
        
        # 提取 organic 结果中的 snippet
        if "organic" in data and isinstance(data["organic"], list):
            for item in data["organic"]:
                if "snippet" in item and item["snippet"]:
                    snippets.append(item["snippet"])
        
        # 返回精简后的内容，只包含 snippets
        return "\n\n".join(snippets) if snippets else result_content
    except (json.JSONDecodeError, KeyError, TypeError):
        # 如果解析失败，返回原始内容
        return result_content

def search(
    query: str,
    *,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    site: Optional[str] = None,

) -> Optional[str]:
    """Search using Tavily web search API."""
    url = "https://api.tavily.com/search"
    authorization = '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'
    headers = {
        "Authorization": f"Bearer {authorization}",
        "Content-Type": "application/json",
    }
    date_filter_message = f" with date range: {start_date} to {end_date}" if start_date and end_date else ""

    try:
        if site:
            query = f"{query} site:{site}"
        payload = {
            "query": query,
            "max_results": 6,
            "include_answer": True,
            "exclude_domains": ["https://huggingface.co"],
        }
        if start_date:
            payload["start_date"] = start_date
        if end_date:
            payload["end_date"] = end_date

        resp = requests.post(url, headers=headers, json=payload)
        if resp.status_code != 200:
            return f"Search API request failed with status code {resp.status_code}. Check your search parameters."
        data = resp.json()
        results = data.get("results", [])
        if not results:
            return f"No results found for '{query}'{date_filter_message}. Try with a more general query, or remove the date filter."
        snippets = [r.get("content", "") for r in results if r.get("content")]
        return "\n\n".join(snippets)

    except Exception as e:
        return f"Search exception: {e}"

class SearchInput(BaseModel):
    query: str = Field(description="a simple query to search, do not include too many key words or quotation marks")
    start_date: Optional[str] = Field(
        default=None,
        description="[Optional]: filter the search results to only include pages from a specific start date.",
    )
    end_date: Optional[str] = Field(
        default=None,
        description="[Optional]: filter the search results to only include pages from a specific end date.",
    )
    site: Optional[str] = Field(
        default=None,
        description="[Optional]: restrict the search to a specific website or domain. For example, 'wikipedia.org' will only return results from wikipedia site.",
    )
    gl: Optional[str] = Field(
        default=None,
        description="[Optional]: the geolocation (country code) for the search results, e.g., 'US' for United States, 'GB' for United Kingdom, 'CN' for China.",
    )
    hl: Optional[str] = Field(
        default=None,
        description="[Optional]: the language code for the search results, e.g., 'en' for English, 'fr' for French, 'de' for German, 'zh-cn' for Simplified Chinese.",
    )

class SearchOutput(BaseModel):
    answer: Optional[str] = Field(default=None, description="summary of the search results")
    results: list = Field(description="list of the search results")

search_tool = StructuredTool.from_function(
    func=search,
    name="serper_search",
    description="""Searches the input query using web search API and returns summaries of top results. """,
    args_schema=SearchInput,
    metadata={
        "args_schema_json": SearchInput.model_json_schema(),
        "output_schema_json": SearchOutput.model_json_schema(),

    },
)



# === 工具 24: HPO 表型与疾病交叉索引工具 ===

class QueryHPOInput(BaseModel):
    """
    HPO 查询工具输入模型
    """
    query_term: str = Field(
        ...,
        description="搜索关键词或 HPO ID。例如: 'HPb', 'Microcytic anemia' 或 'HP:0001935'"
    )


def search_hpo_phenotype(query_term: str):
    """
    使用 OLS4 API 搜索 HPO 表型并获取其关联信息（同步版本）
    """
    url = "https://www.ebi.ac.uk/ols4/api/search"

    # 构建请求参数
    params = {
        "q": query_term,
        "ontology": "hp",          # 限制只在 Human Phenotype Ontology 中搜索
        "type": "class",           # 只搜索类（Class）
        "exact": "false",          # 允许模糊匹配
        "rows": 1,                 # 只取前 1 个结果
        "fieldList": "iri,label,short_form,obo_id,description,annotations",
        "local": "true"
    }

    headers = {
        "Accept": "application/json"
    }

    try:
        with httpx.Client(timeout=10.0) as client:
            response = client.get(url, params=params, headers=headers)
            response.raise_for_status()

        data = response.json()
        results = data.get("response", {}).get("docs", [])

        if not results:
            print(f"未找到与 '{query_term}' 相关的表型。")
            return

        print(f"--- 搜索结果 (查询: {query_term}) ---")

        for doc in results:
            print(f"\n标签 (Label): {doc.get('label')}")
            print(f"编号 (ID): {doc.get('obo_id')}")
            print(f"描述: {doc.get('description', ['无描述'])[0]}")

            # Annotation 中的疾病关联信息
            annotations = doc.get("annotations", {})
            dbxrefs = annotations.get("database_cross_reference", [])

            if dbxrefs:
                print(f"关联疾病/外部库引用: {', '.join(dbxrefs)}")

    except httpx.HTTPStatusError as e:
        print(f"API 请求失败: {e.response.status_code}")
    except Exception as e:
        print(f"发生错误: {str(e)}")


hpo_search_tool = StructuredTool.from_function(
    func=search_hpo_phenotype,   # ✅ 同步函数使用 func=
    name="SEARCH_HPO_PHENOTYPE",
    description="""
【领域：生物医学 / 临床表现】
查询人类表型本体（Human Phenotype Ontology, HPO）。

该工具可将模糊的临床症状描述或缩写映射为标准 HPO 表型术语（HP:xxxx），
并返回其医学定义及潜在的疾病关联（如 OMIM、ORPHA）。

使用场景示例：
1. 缩写解析：输入 "HPb" 或 "anemia"
2. 症状标准化：输入 "Microcytic anemia"
3. 精确查询：输入 "HP:0001935"

注意：
- 返回的 database_cross_reference 字段通常包含 OMIM / ORPHA
- 该字段是连接表型与罕见病的关键信息
""",
    args_schema=QueryHPOInput,
    metadata={"args_schema_json": QueryHPOInput.schema()}
)


# === 工具 25: Ensembl 基因 ID 转换工具 ===

class EnsemblConvertInput(BaseModel):
    """
    Ensembl 转换工具输入模型
    """
    query: str = Field(
        ...,
        description="Ensembl 基因 ID。必须以 'ENSG' 开头，例如: 'ENSG00000161011'"
    )

def query_ensembl_symbol(query: str) -> Dict[str, Any]:
    """
    通过 Ensembl REST API 将 ENSG ID 转换为可读的 Gene Symbol
    """
    # 基础清洗：去除可能存在的空白字符
    ensg = query.strip()
    
    if not ensg.startswith("ENSG"):
        return {
            "success": False, 
            "error": f"Invalid format: '{ensg}'. Ensembl human gene IDs must start with 'ENSG'."
        }

    url = f"https://rest.ensembl.org/lookup/id/{ensg}"
    headers = {"Content-Type": "application/json"}

    try:
        # 使用 timeout 保证 Agent 工作流不会死锁
        response = requests.get(url, headers=headers, timeout=15)
        
        # 处理 404 情况（找不到该 ID）
        if response.status_code == 404:
            return {"success": False, "error": f"Gene ID '{ensg}' not found in Ensembl database."}
            
        response.raise_for_status()
        data = response.json()

        # 提取核心展示名称
        symbol = data.get("display_name")
        description = data.get("description", "No description available")
        biotype = data.get("biotype", "unknown")

        return {
            "success": True,
            "ensg_id": ensg,
            "symbol": symbol,
            "biotype": biotype,
            "description": description,
            "species": data.get("species")
        }

    except requests.exceptions.RequestException as e:
        return {"success": False, "error": f"Network or API error: {str(e)}"}
    except KeyError:
        return {"success": False, "error": "Unexpected API response format."}

# 注册 Ensembl 工具
ensembl_tool = StructuredTool.from_function(
    func=query_ensembl_symbol,
    name='ENSG_TO_SYMBOL_CONVERTER',
    description="""
    【领域：生物信息学/基因组学】
    将 Ensembl 基因稳定标识符 (ENSG ID) 转换为通用的基因符号 (Gene Symbol)。
    
    使用场景与示例：
    1. 唯一标识符解析：当你从差异表达分析、GWAS 研究或 HPO 关联中获得类似 'ENSG00000161011' 的代码时，使用此工具。
    2. 结果示例：输入 'ENSG00000161011'，工具将返回 'HBA1' (Hemoglobin Subunit Alpha 1)，这有助于理解该基因与血红蛋白相关表型（如贫血）的关系。
    
    注意：此工具仅接受以 'ENSG' 开头的 ID。如果 Agent 获得了其他格式（如 Entrez ID 或 Symbol），请寻找其他对应的转换工具。
    工具返回示例：
    {'success': True, 'ensg_id': 'ENSG00000161011', 'symbol': 'SQSTM1', 'biotype': 'protein_coding', 'description': 'sequestosome 1 [Source:HGNC Symbol;Acc:HGNC:11280]', 'species': 'homo_sapiens'}
    """,
    args_schema=EnsemblConvertInput,
    metadata={"args_schema_json": EnsemblConvertInput.schema()}
)



# === 工具 26: Phen2Gene 基因优先级排序工具 ===

class Phen2GeneInput(BaseModel):
    """
    Phen2Gene 工具输入模型
    """
    HPO_list: str = Field(
        ...,
        description="以分号分隔的 HPO ID 列表。例如: 'HP:0002459;HP:0010522;HP:0001662'"
    ),
    model: str = Field(
        ...,
        description="the model to use for the phen2gene ranking, one of 'w', 'ic', 'u', 'sk'"
    )


def query_phen2gene(HPO_list: str, model: str) -> Dict[str, Any]:
    """
    使用 Phen2Gene API 根据 HPO 表型列表对全球基因进行关联得分排序。
    """
    # 基础清洗：确保没有空格且格式正确
    hpo_query = HPO_list.replace(" ", "")
    
    # 固化专家参数：使用 sk (Sk-weighted) 模型，这是该算法中表现较稳健的模型
    url = "https://phen2gene.wglab.org/api"
    params = {
        "HPO_list": hpo_query,
        "weight_model": model
    }
    
    headers = {"Accept": "application/json"}

    try:
        # Phen2Gene 计算量较大，建议设置较长的 timeout
        response = requests.get(url, params=params, headers=headers, timeout=30, verify=False)
        
        if response.status_code == 400:
            return {"success": False, "error": "Invalid HPO ID format or empty list."}
            
        response.raise_for_status()
        data = response.json()

        # Phen2Gene 返回通常是一个包含 'results' 的列表
        # 结果按得分从高到低排列
        raw_results = data.get("results", [])
        
        # 为了防止返回内容过长导致 LLM Token 溢出，我们仅保留 Top 15 个基因
        top_genes = raw_results[:15]

        return {
            "success": True,
            "hpo_used": hpo_query,
            "top_candidates": [
                {
                    "rank": i + 1,
                    "gene_symbol": item.get("Gene"),
                    #"score": item.get("Score"),
                    "ensg_id": item.get("Ensembl")
                } for i, item in enumerate(top_genes)
            ],
            "note": "Results are ranked by association score. Only the top 15 candidates are returned."
        }

    except requests.exceptions.RequestException as e:
        return {"success": False, "error": f"API request failed: {str(e)}"}

# 注册 Phen2Gene 工具
phen2gene_tool = StructuredTool.from_function(
    func=query_phen2gene,
    name='PHENOTYPE_TO_GENE_RANKER',
    description="""
    【领域：计算遗传学/精准医疗】
    根据患者的一系列 HPO 表型术语，通过 Phen2Gene 算法计算并返回最相关的候选基因排名。
    示例：phe_result = query_phen2gene("HP:0000474;HP:0000733;HP:0002354;HP:0002442;HP:0002446;HP:0006892;HP:0010522;HP:0011204;HP:0001250;HP:0002300;HP:0012735;HP:0001347;HP:0000741;HP:0008572;HP:0000554;HP:0012653;HP:0011736;HP:0001025", model="w")

    使用场景与示例：
    1. 临床诊断辅助：当你收集了患者的多个症状（如小头畸形、发育迟缓、先天性心脏病）对应的 HPO ID 后使用。
    2. 参数格式：输入必须是分号分隔的 ID 字符串。示例: 'HP:0002459;HP:0010522;HP:0001662'。
    3. 输出解读：工具返回得分最高的 Top 15 个基因。Agent 应重点关注排名前 3 的基因（如 'FGFR3', 'TTN' 等），并可进一步使用 ENSG 转换工具验证。
    
    工具返回示例：
    {'success': True, 'hpo_used': 'HP:0000474;HP:0000733;HP:0002354;HP:0002442;HP:0002446;HP:0006892;HP:0010522;HP:0011204;HP:0001250;HP:0002300;HP:0012735;HP:0001347;HP:0000741;HP:0008572;HP:0000554;HP:0012653;HP:0011736;HP:0001025', 'top_candidates': [{'rank': 1, 'gene_symbol': 'C9ORF72', 'ensg_id': None}, {'rank': 2, 'gene_symbol': 'CHMP2B', 'ensg_id': None}, {'rank': 3, 'gene_symbol': 'VCP', 'ensg_id': None}, {'rank': 4, 'gene_symbol': 'PSEN1', 'ensg_id': None}, {'rank': 5, 'gene_symbol': 'MAPT', 'ensg_id': None}, {'rank': 6, 'gene_symbol': 'SQSTM1', 'ensg_id': None}, {'rank': 7, 'gene_symbol': 'TREM2', 'ensg_id': None}, {'rank': 8, 'gene_symbol': 'GRN', 'ensg_id': None}, {'rank': 9, 'gene_symbol': 'TMEM106B', 'ensg_id': None}, {'rank': 10, 'gene_symbol': 'PLA2G6', 'ensg_id': None}, {'rank': 11, 'gene_symbol': 'KRAS', 'ensg_id': None}, {'rank': 12, 'gene_symbol': 'PRKAR1B', 'ensg_id': None}, {'rank': 13, 'gene_symbol': 'NF1', 'ensg_id': None}, {'rank': 14, 'gene_symbol': 'FUS', 'ensg_id': None}, {'rank': 15, 'gene_symbol': 'CACNA1A', 'ensg_id': None}], 'note': 'Results are ranked by association score. Only the top 15 candidates are returned.'}
    """,
    args_schema=Phen2GeneInput,
    metadata={"args_schema_json": Phen2GeneInput.schema()}
)