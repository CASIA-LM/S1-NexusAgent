import json
import logging
from typing import Dict, List, Optional, Any
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from workflow import config as science_config

# 引入各个领域的工具集
from workflow.tools import (
    tools as all_tools,
    biology_domain,
    chemistry_domain,
    material_domain
)

class ToolRetriever:
    def __init__(
            self,
            subset_tools: Optional[List] = None,  # 新增：工具子集控制
            llm_model: str = science_config.DeepSeekV3.model,
            base_url: str = science_config.DeepSeekV3.base_url,
            api_key: str = science_config.DeepSeekV3.api_key,
            max_per_category: int = 10,
            enable_domain_filter: bool = True  # 新增：是否启用领域过滤
    ):
        """
        初始化工具检索器

        Args:
            subset_tools: 可选的工具子集。如果提供，只有这些工具可被检索
            llm_model: LLM 模型名称
            base_url: API base URL
            api_key: API key
            max_per_category: 每个类别最大工具数（暂未使用）
            enable_domain_filter: 是否启用领域过滤。如果为 False，忽略 domain_filter
        """
        self.llm_model = llm_model
        self.base_url = base_url
        self.api_key = api_key
        self.max_per_category = max_per_category
        self.enable_domain_filter = enable_domain_filter

        # 核心改进：支持工具子集控制
        self.subset_tools = subset_tools

        # 建立领域到工具集的映射表 (Hard Routing)
        # 如果提供了 subset_tools，则从 subset_tools 中过滤出各领域工具
        if subset_tools is not None:
            self.domain_tool_map = self._build_domain_map_from_subset(subset_tools)
        else:
            # 使用默认的全量工具集
            self.domain_tool_map = {
                "biology": biology_domain,
                "chemistry": chemistry_domain,
                "materials": material_domain,
                "physics": all_tools,
                "general": all_tools,
            }

    def _build_domain_map_from_subset(self, subset_tools: List) -> Dict[str, List]:
        """
        从工具子集构建领域映射

        策略：根据工具名称或描述中的关键词判断领域
        """
        # 创建工具名称到工具对象的映射
        subset_tool_names = {tool.name for tool in subset_tools}

        # 从预定义领域中过滤出在 subset 中的工具
        domain_map = {}

        # Biology 领域
        domain_map["biology"] = [
            tool for tool in biology_domain
            if tool.name in subset_tool_names
        ]

        # Chemistry 领域
        domain_map["chemistry"] = [
            tool for tool in chemistry_domain
            if tool.name in subset_tool_names
        ]

        # Materials 领域
        domain_map["materials"] = [
            tool for tool in material_domain
            if tool.name in subset_tool_names
        ]

        # General 和 Physics 使用全部 subset
        domain_map["general"] = subset_tools
        domain_map["physics"] = subset_tools

        logging.info(f"Built domain map from subset: "
                    f"biology={len(domain_map['biology'])}, "
                    f"chemistry={len(domain_map['chemistry'])}, "
                    f"materials={len(domain_map['materials'])}, "
                    f"general={len(domain_map['general'])}")

        return domain_map

    async def prompt_based_retrieval(
            self,
            retrieval_context: Dict[str, Any]
    ) -> Dict[str, List]:
        """
        基于意图识别产生的结构化上下文进行工具检索。
        """

        # 1. 解析上下文
        domain_filter = retrieval_context.get("domain_filter", "general")
        search_queries = retrieval_context.get("search_queries", [])

        # 2. 领域硬过滤 (Hard Filter)
        if self.enable_domain_filter:
            # 启用领域过滤：根据 domain_filter 选择候选工具集
            candidate_tool_set = self.domain_tool_map.get(domain_filter, self.domain_tool_map.get("general", []))
            logging.info(f"Domain filter enabled: {domain_filter}, candidate tools: {len(candidate_tool_set)}")
        else:
            # 禁用领域过滤：使用全部可用工具（subset_tools 或 general）
            if self.subset_tools is not None:
                candidate_tool_set = self.subset_tools
            else:
                candidate_tool_set = self.domain_tool_map.get("general", all_tools)
            logging.info(f"Domain filter disabled, using all available tools: {len(candidate_tool_set)}")

        # 边界检查：如果候选工具集为空，返回空结果
        if not candidate_tool_set:
            logging.warning(f"No candidate tools found for domain: {domain_filter}")
            return {"tools": []}

        # 3. 格式化工具描述
        formatted_tools = self._format_tools(candidate_tool_set)

        # 4. 构造高精度 Prompt
        tasks_str = "\n".join([f"- Task {i+1}: {q}" for i, q in enumerate(search_queries)])

        system_prompt = (
            "你是一个专业的科研工具库管理员。你的任务是根据用户的科研目标和具体步骤，"
            "从给定的工具列表中筛选出最合适的工具。"
        )

        user_prompt = f"""
# System Prompt
你是一个由于极高准确率而闻名的科研工具检索系统。
你的唯一目标是：基于用户的**具体执行步骤**，从候选列表中选出**必须**的工具。

# User Prompt Template

## 1. 任务分析上下文
领域范围: {domain_filter} (请忽略非此领域的专用工具)

待解决的子任务清单:
{tasks_str}
(例如:
 - Task 1: 从给定的9个基因中识别与淋巴瘤相关的致病基因 -> 需要: 疾病关联数据库
 - Task 2: 基因功能注释 -> 需要: 基因注释API
)

## 2. 候选工具库
{formatted_tools}

## 3. 选择标准 (Thinking Process)
请按照以下步骤思考：
1. 逐一阅读每个"待解决的子任务"。
2. 在工具库中寻找描述（Description）与该子任务强相关的工具。
3. **负面过滤**: 如果工具是用来做"分子对接"的，但任务是"基因筛选"，绝对不要选。
4. **通用兜底**: 如果任务需要搜索最新信息且没有专用工具，选择 `web_search` (如果有)。
5. **最小化原则**: 只选择完成任务必需的工具，避免选择功能重复的工具。

## 4. 输出要求
Strict JSON only. 不要解释。
格式:
{{
  "thought": "任务1需要查询疾病关联，匹配到 [3] DisGeNET工具；任务2需要注释，匹配到 [5] MyGeneInfo...",
  "tool_indices": [3, 5, ...]
}}
"""

        # 5. 调用 LLM
        llm = ChatOpenAI(
            model=self.llm_model,
            base_url=self.base_url,
            api_key=self.api_key,
            temperature=0.3
        )

        resp = await llm.ainvoke([
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_prompt)
        ])

        # 6. 解析结果
        selected_indices = self._parse_response(resp.content)

        # 7. 映射回工具对象（添加去重）
        selected_tools = []
        seen_tool_names = set()

        for idx in selected_indices:
            if 0 <= idx < len(candidate_tool_set):
                tool = candidate_tool_set[idx]
                # 去重：避免重复添加同名工具
                if tool.name not in seen_tool_names:
                    selected_tools.append(tool)
                    seen_tool_names.add(tool.name)
                else:
                    logging.debug(f"Skipping duplicate tool: {tool.name}")

        logging.info(f"Retrieved {len(selected_tools)} unique tools from {len(selected_indices)} indices")
        return {"tools": selected_tools}

    def _format_tools(self, tools_list: List) -> str:
        """生成带索引的工具描述列表"""
        lines = []
        for i, tool in enumerate(tools_list):
            # 截断过长的描述
            description = tool.description
            if len(description) > 200:
                description = description[:200] + "..."
            lines.append(f"[{i}] {tool.name}: {description}")
        return "\n".join(lines)

    def _parse_response(self, content: str) -> List[int]:
        """解析 JSON 输出"""
        try:
            # 尝试找到 JSON 块
            if "```json" in content:
                content = content.split("```json")[1].split("```")[0]
            elif "```" in content:
                content = content.split("```")[1].split("```")[0]

            data = json.loads(content.strip())
            indices = data.get("tool_indices", [])

            # 验证索引类型
            if not isinstance(indices, list):
                logging.error(f"tool_indices is not a list: {type(indices)}")
                return []

            # 过滤非整数索引
            valid_indices = [idx for idx in indices if isinstance(idx, int)]
            if len(valid_indices) != len(indices):
                logging.warning(f"Filtered out {len(indices) - len(valid_indices)} non-integer indices")

            return valid_indices

        except Exception as e:
            logging.error(f"Error parsing tool retrieval: {e}")
            return []
