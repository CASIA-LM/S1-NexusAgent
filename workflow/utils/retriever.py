from typing import List, Dict, Optional
import os
import re
from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage

#from biomni.utils import process_bio_retrieval_document

class ToolRetriever:
    """Retrieve tools from the tool registry via prompt-based LLM filtering."""

    def __init__(self,
                 llm_model: str = "DeepSeekV3",
                 max_per_category: int = 5, # 控制返回的工具个数
                 base_url: str = "",
                 api_key: str = ""
                 ):
        if api_key is None:
            api_key = os.getenv("OPENAI_API_KEY")
            if api_key is None:
                raise ValueError("API key must be provided via parameter or OPENAI_API_KEY environment variable.")

        self.llm_model = llm_model
        self.max_per_category = max_per_category
        self.base_url = base_url
        self.api_key = api_key



    # 工具检索主程序: prompt_based_retrieval
    # 返回示例：

    """

    query: 用户输入的query
    resources: 所有工具的工具名称、工具描述、参数描述；

    ##代码使用##：
    selected_resources = self.retriever.prompt_based_retrieval(query, resources, llm="defult")   
    selected_resources_names = {
        'tools': selected_resources['tools'],
        'data_lake': [],
        'libraries': [lib['name'] if isinstance(lib, dict) else lib for lib in selected_resources['libraries']]
    }
    
    ##输出结果##：
    ####### selected_resources_names ########## 
    # {'tools': [{'description': 'Query the UniProt REST API using either natural language or a direct endpoint.', 'name': 'query_uniprot', 'optional_parameters': [{'default': None, 'description': 'Full or partial UniProt API endpoint URL to query directly (e.g., "https://rest.uniprot.org/uniprotkb/P01308")', 'name': 'endpoint', 'type': 'str'}, {'default': None, 'description': 'Anthropic API key. If None, will use ANTHROPIC_API_KEY env variable', 'name': 'api_key', 'type': 'str'}, {'default': 'claude-3-5-haiku-20241022', 'description': 'Anthropic model to use for natural language processing', 'name': 'model', 'type': 'str'}, {'default': 5, 'description': 'Maximum number of results to return', 'name': 'max_results', 'type': 'int'}], 'required_parameters': [{'default': None, 'description': 'Natural language query about proteins (e.g., "Find information about human insulin")', 'name': 'prompt', 'type': 'str'}],
    #  'id': 144}, {'description': 'Query the AlphaFold Database API for protein structure predictions.', 'name': 'query_alphafold', 'optional_parameters': [{'default': 'prediction', 'description': 'Specific AlphaFold API endpoint to query: "prediction", "summary", or "annotations"', 'name': 'endpoint', 'type': 'str'}, {'default': None, 'description': 'Specific residue range in format "start-end" (e.g., "1-100")', 'name': 'residue_range', 'type': 'str'}, {'default': False, 'description': 'Whether to download structure files', 'name': 'download', 'type': 'bool'}, {'default': None, 'description': 'Directory to save downloaded files', 'name': 'output_dir', 'type': 'str'}, {'default': 'pdb', 'description': 'Format of the structure file to download - "pdb" or "cif"', 'name': 'file_format', 'type': 'str'}, {'default': 'v4', 'description': 'AlphaFold model version - "v4" (latest) or "v3", "v2", "v1"', 'name': 'model_version', 'type': 'str'}, {'default': 1, 'description': 'Model number (1-5, with 1 being the highest confidence model)', 'name': 'model_number', 'type': 'int'}], 'required_parameters': [{'default': None, 'description': 'UniProt accession ID (e.g., "P12345")', 'name': 'uniprot_id', 'type': 'str'}], 
    # 'id': 145}, {'description': 'Query the RCSB PDB database using natural language or a direct structured query.', 'name': 'query_pdb', 'optional_parameters': [{'default': None, 'description': 'Direct structured query in RCSB Search API format (overrides prompt)', 'name': 'query', 'type': 'dict'}, {'default': None, 'description': 'Anthropic API key. If None, will use ANTHROPIC_API_KEY env variable', 'name': 'api_key', 'type': 'str'}, {'default': 'claude-3-5-haiku-20241022', 'description': 'Anthropic model to use for natural language processing', 'name': 'model', 'type': 'str'}, {'default': 3, 'description': 'Maximum number of results to return', 'name': 'max_results', 'type': 'int'}], 'required_parameters': [{'default': None, 'description': 'Natural language query about protein structures', 'name': 'prompt', 'type': 'str'}],
    #  'id': 147}, {'description': 'Retrieve detailed data and/or download files for PDB identifiers.', 'name': 'query_pdb_identifiers', 'optional_parameters': [{'default': 'entry', 'description': "Type of results: 'entry', 'assembly', 'polymer_entity', etc.", 'name': 'return_type', 'type': 'str'}, {'default': False, 'description': 'Whether to download PDB structure files', 'name': 'download', 'type': 'bool'}, {'default': None, 'description': 'List of specific attributes to retrieve', 'name': 'attributes', 'type': 'List[str]'}], 'required_parameters': [{'default': None, 'description': 'List of PDB identifiers to query', 'name': 'identifiers', 'type': 'List[str]'}], 
    # 'id': 148}, {'description': 'Compares two protein structures to identify structural differences and conformational changes.', 'name': 'compare_protein_structures', 'optional_parameters': [{'default': 'A', 'description': 'Chain ID to analyze in the first structure', 'name': 'chain_id1', 'type': 'str'}, {'default': 'A', 'description': 'Chain ID to analyze in the second structure', 'name': 'chain_id2', 'type': 'str'}, {'default': 'protein_comparison', 'description': 'Prefix for output files', 'name': 'output_prefix', 'type': 'str'}], 'required_parameters': [{'default': None, 'description': 'Path to the first PDB file', 'name': 'pdb_file1', 'type': 'str'}, {'default': None, 'description': 'Path to the second PDB file', 'name': 'pdb_file2', 'type': 'str'}], 
    # 'id': 140}], 
    # 'data_lake': [], 'libraries': ['biopython', 'biotite', 'rdkit', 'viennarna', 'autosite']}
    """
    def prompt_based_retrieval(self,
                               query: str,
                               resources: Dict[str, List],
                               llm: Optional[ChatOpenAI] = None
                               ) -> Dict[str, List]:
        """
        Retrieve the top-N relevant resources per category using only LLM-based filtering.

        Args:
            query: User's natural-language query
            resources: Dict with keys 'tools', 'data_lake', 'libraries'
            llm: Optional custom LLM instance
        Returns:
            Dict of same keys with up to max_per_category items each
        """
        # Build and send prompt
        prompt = self._build_prompt(query, resources)
        if llm == "defult":
            llm = ChatOpenAI(
                model=self.llm_model,
                base_url=self.base_url,
                temperature=0.3,
                api_key=self.api_key
            )
        response = llm.invoke([HumanMessage(content=prompt)]) if hasattr(llm, 'invoke') else llm(prompt)
        resp_content = response.content if hasattr(response, 'content') else str(response)
        selected = self._parse_llm_response(resp_content)

        # Gather selected resources in returned order
        result = {}
        for cat in ['tools', 'data_lake', 'libraries']:
            idxs = selected.get(cat, [])[:self.max_per_category]
            items = resources.get(cat, [])
            # Respect LLM order: most relevant first
            result[cat] = [items[i] for i in idxs if 0 <= i < len(items)]
        return result



    def _build_prompt(self, query: str, resources: Dict[str, List]) -> str:
        """Construct LLM prompt enforcing maximum items per category and relevance ordering."""
        sections = []
        for cat in ['tools', 'data_lake', 'libraries']:
            formatted = self._format_resources_for_prompt(resources.get(cat, []))
            sections.append(f"AVAILABLE {cat.upper()} ({len(resources.get(cat, []))} items):\n" + formatted)

        prompt = (
            f"You are a precise biomedical research assistant.\n"
            f"Select the MOST relevant resources for the user's query.\n"  # 提示llm，按相关性降序排列索引（最相关的在前）” 的指令，确保 LLM 输出的索引列表已按优先级排序。
            f"Return NO MORE than {self.max_per_category} items per category, and list the indices SORTED by relevance (most relevant first).\n"
            f"Respond in strict JSON with format: {{tools: [indices], data_lake: [...], libraries: [...]}}.\n\n"
            f"USER QUERY: {query}\n\n"
            + "\n\n".join(sections)
        )
        return prompt

    def _format_resources_for_prompt(self, resources: list) -> str:
        """Format resources with index, name, and description."""
        if not resources:
            return "None"
        lines = []
        for i, item in enumerate(resources):
            if isinstance(item, dict):
                name = item.get('name', '')
                desc = item.get('description', '')[:100]
                lines.append(f"{i}: {name} - {desc}")
            else:
                lines.append(f"{i}: {str(item)}")
        return "\n".join(lines)

    def _parse_llm_response(self, response: str) -> Dict[str, List[int]]:
        """Extract index lists from JSON-like or plain text response."""
        # Try JSON eval
        try:
            data = eval(response, {})
            return {k: data.get(k, []) for k in ['tools', 'data_lake', 'libraries']}
        except Exception:
            # Fallback regex
            return self._regex_parse(response)

    def _regex_parse(self, response: str) -> Dict[str, List[int]]:
        selected = {'tools': [], 'data_lake': [], 'libraries': []}
        for cat in selected:
            match = re.search(fr'"?{cat}"?[\s\:]*\[([^\]]*)\]', response, re.IGNORECASE)
            if match and match.group(1).strip():
                try:
                    selected[cat] = [int(x.strip()) for x in match.group(1).split(',') if x.strip()]
                except ValueError:
                    pass
        return selected
