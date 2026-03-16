
你是专家，我的需求，请你参考示例代码，转换“## 待转换的tools”符合我的要求，框架为langgraph，优化工具描述和工具输入描述，目标是agent更好调用；
## 要求
1. 工具描述等信息，语言全部为英文；
2. 按照示例格式，进行转换；
3. 转换后请你保存当前目录，命名为：biomini_eval_tools.py
4. 请你确保转换后的tools能直接调用成功；

## 其他
 1. _query_llm_for_api 为 _query_claude_for_api
 2. _query_rest_api 为 _query_rest_api

## 示例tools代码
'''python
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
'''

## 我已经实现的部分代码
’‘’python
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
    
'''




## 待转换的tools
‘’‘python
def query_dbsnp(
    prompt=None,
    search_term=None,
    max_results=3,
):
    """Query the NCBI dbSNP database using natural language or a direct search term.

    Parameters
    ----------
    prompt (str, required): Natural language query about genetic variants/SNPs
    search_term (str, optional): Direct search term in dbSNP syntax
    max_results (int): Maximum number of results to return

    Returns
    -------
    dict: Dictionary containing the query results or error information

    Examples
    --------
    - Natural language: query_dbsnp("Find pathogenic variants in BRCA1")
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
        llm_result = _query_llm_for_api(
            prompt=prompt,
            schema=dbsnp_schema,
            system_template=system_template,
        )

        if not llm_result["success"]:
            return llm_result

        # Get the search term from Claude's response
        query_info = llm_result["data"]
        search_term = query_info.get("search_term", "")

        if not search_term:
            return {
                "error": "Failed to generate a valid search term from the prompt",
                "llm_response": llm_result.get("raw_response", "No response"),
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
    prompt (str, required): Natural language query about genomic data
    endpoint (str, optional): Direct API endpoint to query (e.g., "lookup/symbol/human/BRCA2") or full URL
    verbose (bool): Whether to return detailed results

    Returns
    -------
    dict: Dictionary containing the query results or error information

    Examples
    --------
    - Natural language: query_ensembl("Get information about the human BRCA2 gene")
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
        llm_result = _query_llm_for_api(
            prompt=prompt,
            schema=ensembl_schema,
            system_template=system_template,
        )

        if not llm_result["success"]:
            return llm_result

        # Get the endpoint and parameters from Claude's response
        query_info = llm_result["data"]
        endpoint = query_info.get("endpoint", "")
        params = query_info.get("params", {})
        description = query_info.get("description", "")

        if not endpoint:
            return {
                "error": "Failed to generate a valid endpoint from the prompt",
                "llm_response": llm_result.get("raw_response", "No response"),
            }
    else:
        # Process provided endpoint
        if endpoint.startswith("http"):
            # If a full URL is provided, extract the endpoint part
            if endpoint.startswith(base_url):
                endpoint = endpoint[len(base_url) :].lstrip("/")

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
    api_result = _query_rest_api(
        endpoint=url,
        method="GET",
        params=params,
        headers=headers,
        description=description,
    )

    # Format the results if successful
    if not verbose and "success" in api_result and api_result["success"] and "result" in api_result:
        return _format_query_results(api_result["result"])

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
    prompt (str, required): Natural language query about drug targets, diseases, and mechanisms
    query (str, optional): Direct GraphQL query string
    variables (dict, optional): Variables for the GraphQL query
    verbose (bool): Whether to return detailed results

    Returns
    -------
    dict: Dictionary containing the query results or error information

    Examples
    --------
    - Natural language: query_opentarget("Find drug targets for Alzheimer's disease")
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
        llm_result = _query_llm_for_api(
            prompt=prompt,
            schema=opentarget_schema,
            system_template=system_template,
        )

        if not llm_result["success"]:
            return llm_result

        # Get the query and variables from Claude's response
        query_info = llm_result["data"]
        query = query_info.get("query", "")
        if variables is None:  # Only use Claude's variables if none provided
            variables = query_info.get("variables", {})

        if not query:
            return {
                "error": "Failed to generate a valid GraphQL query from the prompt",
                "llm_response": llm_result.get("raw_response", "No response"),
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
    prompt (str, required): Natural language query about GWAS data
    endpoint (str, optional): Full API endpoint to query (e.g., "https://www.ebi.ac.uk/gwas/rest/api/studies?diseaseTraitId=EFO_0001360")
    max_results (int): Maximum number of results to return

    Returns
    -------
    dict: Dictionary containing the query results or error information

    Examples
    --------
    - Natural language: query_gwas_catalog("Find GWAS studies related to Type 2 diabetes")
    - Direct endpoint: query_gwas_catalog(endpoint="studies", params={"diseaseTraitId": "EFO_0001360"})

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
        llm_result = _query_llm_for_api(
            prompt=prompt,
            schema=gwas_schema,
            system_template=system_template,
        )

        if not llm_result["success"]:
            return llm_result

        # Get the endpoint and parameters from Claude's response
        query_info = llm_result["data"]
        endpoint = query_info.get("endpoint", "")
        params = query_info.get("params", {})
        description = query_info.get("description", "")

        if not endpoint:
            return {
                "error": "Failed to generate a valid endpoint from the prompt",
                "llm_response": llm_result.get("raw_response", "No response"),
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



def query_uniprot(
    prompt=None,
    endpoint=None,
    max_results=5,
):
    """Query the UniProt REST API using either natural language or a direct endpoint.

    Parameters
    ----------
    prompt (str, required): Natural language query about proteins (e.g., "Find information about human insulin")
    endpoint (str, optional): Full or partial UniProt API endpoint URL to query directly
                            (e.g., "https://rest.uniprot.org/uniprotkb/P01308")
    max_results (int): Maximum number of results to return

    Returns
    -------
    dict: Dictionary containing the query information and the UniProt API results

    Examples
    --------
    - Natural language: query_uniprot(prompt="Find information about human insulin protein")
    - Direct endpoint: query_uniprot(endpoint="https://rest.uniprot.org/uniprotkb/P01308")

    """
    # Base URL for UniProt API
    base_url = "https://rest.uniprot.org"

    # Ensure we have either a prompt or an endpoint
    if prompt is None and endpoint is None:
        return {"error": "Either a prompt or an endpoint must be provided"}

    # If using prompt, parse with Claude
    if prompt:
        # Load UniProt schema
        schema_path = os.path.join(os.path.dirname(__file__), "schema_db", "uniprot.pkl")
        with open(schema_path, "rb") as f:
            uniprot_schema = pickle.load(f)

        # Create system prompt template
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

        # Query Claude to generate the API call
        llm_result = _query_llm_for_api(
            prompt=prompt,
            schema=uniprot_schema,
            system_template=system_template,
        )

        if not llm_result["success"]:
            return llm_result

        # Get the full URL from Claude's response
        query_info = llm_result["data"]
        endpoint = query_info.get("full_url", "")
        description = query_info.get("description", "")

        if not endpoint:
            return {
                "error": "Failed to generate a valid endpoint from the prompt",
                "llm_response": llm_result.get("raw_response", "No response"),
            }
    else:
        # Use provided endpoint directly
        if endpoint.startswith("/"):
            endpoint = f"{base_url}{endpoint}"
        elif not endpoint.startswith("http"):
            endpoint = f"{base_url}/{endpoint.lstrip('/')}"
        description = "Direct query to provided endpoint"

    # Use the common REST API helper function
    api_result = _query_rest_api(endpoint=endpoint, method="GET", description=description)

    return api_result



def advanced_web_search_claude(
    query: str,
    max_searches: int = 1,
    max_retries: int = 3,
) -> tuple[str, list[dict[str, str]], list]:
    """
    Initiate an advanced web search by launching a specialized agent to collect relevant information and citations through multiple rounds of web searches for a given query.
    Craft the query carefully for the search agent to find the most relevant information.

    Parameters
    ----------
    query : str
        The search phrase you want Claude to look up.
    max_searches : int, optional
        Upper-bound on searches Claude may issue inside this request.
    max_retries : int, optional
        Maximum number of retry attempts with exponential backoff.

    Returns
    -------
    full_text : str
        A formatted string containing the full text response from Claude and the citations.
    """
    import random

    import anthropic

    try:
        from biomni.config import default_config

        model = default_config.llm
        api_key = default_config.api_key
        if not api_key:
            api_key = os.getenv("ANTHROPIC_API_KEY")
    except ImportError:
        model = "claude-4-sonnet-latest"
        api_key = os.getenv("ANTHROPIC_API_KEY")

    if "claude" not in model:
        raise ValueError("Model must be a Claude model.")

    if not api_key:
        raise ValueError("Set your api_key explicitly.")

    client = anthropic.Anthropic(api_key=api_key)
    tool_def = {
        "type": "web_search_20250305",
        "name": "web_search",
        "max_uses": max_searches,
    }

    delay = random.randint(1, 10)

    for attempt in range(1, max_retries + 1):
        try:
            response = client.messages.create(
                model=model,
                max_tokens=4096,
                messages=[{"role": "user", "content": query}],
                tools=[tool_def],
            )

            paragraphs, citations = [], []
            response.content = response.content
            formatted_response = ""
            for blk in response.content:
                if blk.type == "text":
                    paragraphs.append(blk.text)
                    formatted_response += blk.text

                    if blk.citations:
                        for cite in blk.citations:
                            citations.append({"url": cite.url, "title": cite.title, "cited_text": cite.cited_text})
                            formatted_response += f"(Citation: {cite.title} - {cite.url})"
            return formatted_response

        except Exception as e:
            if attempt < max_retries:
                time.sleep(delay)
                delay *= 2
                continue
            print(f"Error performing web search after {max_retries} attempts: {str(e)}")
            return f"Error performing web search after {max_retries} attempts: {str(e)}"



def query_arxiv(query: str, max_papers: int = 10) -> str:
    """Query arXiv for papers based on the provided search query.

    Parameters
    ----------
    - query (str): The search query string.
    - max_papers (int): The maximum number of papers to retrieve (default: 10).

    Returns
    -------
    - str: The formatted search results or an error message.

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
    - query (str): The search query string.

    Returns
    -------
    - str: The first search result formatted or an error message.

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
    - query (str): The search query string.
    - max_papers (int): The maximum number of papers to retrieve (default: 10).
    - max_retries (int): Maximum number of retry attempts with modified queries (default: 3).

    Returns
    -------
    - str: The formatted search results or an error message.

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


def search_google(query: str, num_results: int = 3, language: str = "en") -> list[dict]:
    """Search using Google search.

    Args:
        query (str): The search query (e.g., "protocol text or seach question")
        num_results (int): Number of results to return (default: 10)
        language (str): Language code for search results (default: 'en')
        pause (float): Pause between searches to avoid rate limiting (default: 2.0 seconds)

    Returns:
        List[dict]: List of dictionaries containing search results with title and URL

    """
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
    return results_string
'''