import ast
import re
import uuid
import time
import json
# import jsonlines

# tool_table_path = "tool_table.json"

# def load_formatted_json(file_path):
#     """
#     读取整个文件内容，并将其解析为一个 Python 字典
#     """
#     try:
#         with open(file_path, 'r', encoding='utf-8') as f:
#             # 1. 读取整个文件内容为一个字符串
#             json_string = f.read()

#             # 2. 使用 json.loads() 解析整个字符串
#             restored_data = json.loads(json_string)

#             return restored_data
#     except FileNotFoundError:
#         print(f"错误：文件未找到 at {file_path}")
#         return None
#     except json.JSONDecodeError as e:
#         print(f"JSON 解析错误：文件内容可能不是一个完整的 JSON 对象。错误详情: {e}")
#         return None


# def load_tool_table(file_path):
#     tool_list = load_formatted_json(file_path)
#     tool_table = dict()
#     for t in tool_list:
#         for s in t["scenes"]:
#             tool_table[s["scene_name"]] = t["tool_id"]
#     return tool_table


# ToolTable = load_tool_table(tool_table_path)

def tool_name2id(tool_name, ToolTable):
    if tool_name in ToolTable:
        return ToolTable[tool_name]
    else:
        return tool_name

class AgentStep():
    def __init__(self, id, name="智能体"):
        self.id = id
        self.type = "agent"
        self.position = {"x":0, "y":0}
        self.data = {
            "label":name,
            "model":"",
            "tools":[],
            "mcp_tools":[],
            "sys_tools":[],
            "provider":"",
            "temperature":0.3,
            "userMessage":"",
            "systemMessage":"",
            "retrievalTools":[],
            "knowledge_tools":[]
        }

class LlmStep():
    def __init__(self, id, name="大模型"):
        self.id = id
        self.type = "llm"
        self.position = {"x":0, "y":0}
        self.data = {
            "label":name,
            "model":"",
            "temperature":0.3,
            "systemMessage":""
        }

class CodeStep():
    def __init__(self, id, name="代码执行"):
        self.id = id
        self.type = "code"
        self.position = {"x":0, "y":0}
        self.data = {
            "label":name,
            "language":"python",
            "args":[],
            "code":'''def main():\n    return {"res":""}\n'''
        }

class StartStep():
    def __init__(self):
        self.id = "start"
        self.type = "start"
        self.position = {"x":0, "y":0}
        self.data = {
            "label":"Start",
        }
class EndStep():
    def __init__(self):
        self.id = "end"
        self.type = "end"
        self.position = {"x":0, "y":0}
        self.data = {
            "label":"End",
        }

class Flock():
    def __init__(self):
        self.name = "DefaultGraph_"+str(uuid.uuid4())
        self.description = "自动创建的默认图表"
        self.config = {
            "id":str(uuid.uuid4()),
            "name":"Flow Visualization",
            "nodes":[],
            "edges":[],
            "metadata":{
                "entry_point":"",
                "start_connections": [],
                "end_connections": []
            }
        }
        self.updated_at = self.get_updated_at()

    def get_updated_at(self):
        from datetime import datetime, timezone
        now_utc = datetime.now(timezone.utc)
        iso_time_str = now_utc.isoformat(timespec="milliseconds")
        return iso_time_str.replace('+00:00', 'Z')


EXECUTE_PROMPT = '''You are executing a specific step in a multi-step scientific plan.
You will receive:
1. The original user question
2. The whole execution plan 
3. Prior historical context (from the previous step) 
4. **The current step to perform**
Focus ONLY on the current step【当前计划步骤】.
Use the historical context as reference ONLY.
If tool usage is needed, call ONLY the one specified tool.
NEVER guess or call multiple tools.

【用户问题】
{query}
【完整任务计划】
{overall_plan}

【历史步骤执行摘要】
{history_sum}

【当前计划步骤】
{current_plan}


'''

SUPERVISOR_PROMPT = '''You are given the following information regarding a tool or model invocation:
- User instruction for tool/model invocation:  
  {current_plan}
- Tool/model name used ("None" for model invoke):  
  {current_tool}
- Raw invocation output/result:  
  {agent_response}
Your task:
1. Analyze the information above carefully.
2. According to the language specified by **zh-CN**, fill in the following JSON fields:
    - **instruction**: Copy the original user instruction above.
    - **tool_name**: Fill with the tool's name used. Just the same as the given one.
    - **abstract**: Write a informable summary of the invocation **result**.
      - For tool invocation, write a summary of the tool's output/result. Please **retain critical information and data**.
      - For model invocation, write a summary of the model's output/result.
      - If the invocation failed or encountered an error, write a summary of the error.
    - **invoke_status**: Judge if the invocation result was positive. 
      - For successful tool invoke or positive model response, set "success"; 
      - For invoke failure or error, set "failed". 
      - For negetive model response, set "failed".
**Output the result as a JSON object in the following format (replace the example values accordingly):**
```json
{{
  "instruction": "Send an email to Alice about the meeting.",
  "tool_name": "email_sender",
  "abstract": "The email to Alice was sent successfully and she has received the meeting details.",
  "invoke_status": "success"
}}
```
**Rules:**
- All content must be in the language defined by **zh-CN**.
- Only output the JSON object.
- Your JSON object output must contain and only contain the provided JSON field names and structure.


'''


FORMATTER_CODE = '''
def main(arg1 = {argument}) -> dict:
    def json_parsing(input_string):
        input_string = input_string.strip()
        PREFIX = "```json\\n"
        if input_string.startswith(PREFIX):  
            input_string = input_string[len(PREFIX):].strip()
        if input_string.endswith("```"):
            input_string = input_string[:-3].strip()
        import json
        try:
            parsed_data = json.loads(input_string)
        except:
            parsed_data = input_string
        return parsed_data

    js = json_parsing(arg1)
    task = "执行任务：" + js["instruction"]
    status = "执行状态：成功" if js["invoke_status"] == "success" else "执行状态：失败"
    abstract = "执行结果总结：" + js["abstract"]
    out = task+"\\n\\n"+status+"\\n\\n"+abstract

    return {{"res": out}}
'''

SUMMARY_PROMPT = '''你是一位科研助理，现有一个科研问题、专家的解决规划和该份规划的执行记录，请你利用这些信息，针对提供的科研问题整理一份结构化、专业且去重的总结报告。
科研问题：{query}
规划步骤：
{overall_plan}
执行记录：
{history_sum}

请严格遵守以下要求：
1. 报告标题与定位（必选）：
   - 将报告命名为“总结报告”，突出最终概览与关键要点。
2. 报告结构：
   - 背景（Background）：简要说明研究问题和目的。
   - 方法（Methods）：详列调用的每一个工具及其关键参数，并对每个工具的输出结果进行概述。
     * 如果工具执行了代码生成（execute 类型查询），请在此部分引用生成的代码片段，注明代码功能与出处。
   - 结果（Results）：以要点形式呈现所有工具的关键输出，包括数据、图表、模型预测或代码示例等，确保逻辑连贯。
   - 分析与讨论（Discussion）：针对结果进行深入解释，讨论各工具输出的关联性与局限性，以及潜在改进方向。
   - 结论与建议（Conclusion & Recommendations）：尝试根据上述内容解答科研问题，做出总结，并给出后续行动建议。
3. 去重与精炼：
   - 同一信息只保留一次。
   - 严禁整段复制对话原文，须用专业语言进行归纳。
4. 链接 管理：
   - 仅引用对话中由工具真实输出的 URL，格式示例：
     [图表下载链接](https://…)
   - 对所有引用链接，务必标注其在对话中的出处及用途，例如：“图 1 （工具 XYZ 输出）”。
5. 引用与标注：
   - 对所有工具输出（包括 URL、图表和代码片段）进行明确引用，格式示例：
     [图 1 （工具 X 输出）]、```python# 代码片段示例（工具 Y 核心逻辑）```
6. 语言风格：
   - 专业、清晰、简洁，避免口语化表达。
报告语言：zh-CN


'''

def format_trace_to_flock(data, ToolTable):
    query = data["question"]
    trace = data["trace"]

    last_planner_idx = len(trace) - 1
    for node_dict in reversed(trace):
        if "unknown_planner" in node_dict.keys():
            break
        else:
            last_planner_idx -= 1
    shown_trace = trace[last_planner_idx:]

    planner = shown_trace[0]
    plan_steps = [d for d in planner["unknown_planner"]["cur_plan"]] #Dict["content":str, "tool_name":str]

    supervisor_list, execute_list = [], []
    for node in shown_trace[1:]:
        if "unknown_supervisor" in node.keys():
            supervisor_list.append(node)
        if "unknown_execute" in node.keys():
            execute_list.append(node)

    assert(len(supervisor_list) - 1 == len(execute_list) == len(plan_steps))
    flock_step_idx = 1
    position_y = 0
    FLOCK_NODES = [StartStep()]
    for plan_step_idx in range(len(plan_steps)):
        position_x = 250
        current_plan = plan_steps[plan_step_idx]
        current_plan_content = current_plan["content"]
        if "tool_name" in current_plan.keys():
            current_plan_tool = current_plan["tool_name"]
        else:
            current_plan_tool = "None"

        supervisor = supervisor_list[plan_step_idx]
        execute = execute_list[plan_step_idx]
        overall_plan_content = supervisor["unknown_supervisor"]["plan_checklist"]
        if plan_step_idx == 0:
            history_sum_content = "没有执行记录。"
        else:
            i = 0
            history_sum_content = ""
            for node in FLOCK_NODES:
                if node.type == "code":
                    i += 1
                    history_sum_content += f"步骤{str(i)}：\n{{{node.id}.code_result}}\n\n"

        execute_node_id = f"agent-{flock_step_idx}"
        agent_node = AgentStep(execute_node_id, name=f"步骤{plan_step_idx+1}-executor")
        agent_node.position["x"], agent_node.position["y"] = position_x, position_y
        agent_node.data["model"] = "DeepSeekV3"
        agent_node.data["temperature"] = 0.3
        agent_node.data["sys_tools"] = [tool_name2id(current_plan_tool, ToolTable)]
        agent_node.data["systemMessage"] = EXECUTE_PROMPT.format(query="{start.query}",
                                                                 overall_plan=overall_plan_content,
                                                                 history_sum=history_sum_content,
                                                                 current_plan=current_plan_content)
        FLOCK_NODES.append(agent_node)
        flock_step_idx += 1
        position_x += 250

        supervisor_node_id = f"llm-{flock_step_idx}"
        llm_node = LlmStep(supervisor_node_id, name=f"步骤{plan_step_idx + 1}-supervisor")
        llm_node.position["x"], llm_node.position["y"] = position_x, position_y
        llm_node.data["model"] = "DeepSeekV3"
        llm_node.data["temperature"] = 0.3
        llm_node.data["systemMessage"] = SUPERVISOR_PROMPT.format(current_plan=current_plan_content,
                                                                  current_tool=current_plan_tool,                                                                     overall_plan=overall_plan_content,
                                                                  agent_response=f"{{{execute_node_id}.response}}")
        FLOCK_NODES.append(llm_node)
        flock_step_idx += 1
        position_x += 250

        code_node = CodeStep(f"code-{flock_step_idx}", name=f"步骤{plan_step_idx + 1}-formatter")
        code_node.position["x"], code_node.position["y"] = position_x, position_y
        code_node.data["args"] = [{"name":"arg1", "value":f"{supervisor_node_id}.response"}]
        code_node.data["code"] = FORMATTER_CODE.format(argument=f"{{{supervisor_node_id}.response}}")
        FLOCK_NODES.append(code_node)
        flock_step_idx += 1

        position_y += 250


    summary_node_id = f"llm-{flock_step_idx}"
    llm_node = LlmStep(summary_node_id, name="unknown_summary")
    llm_node.position["y"] = position_y
    llm_node.data["model"] = "DeepSeekV3"
    llm_node.data["temperature"] = 0.2
    i = 0
    history_sum_content = ""
    for node in FLOCK_NODES:
        if node.type == "code":
            i += 1
            history_sum_content += f"步骤{str(i)}：\n{{{node.id}.code_result}}\n\n"
    llm_node.data["systemMessage"] = SUMMARY_PROMPT.format(query="{start.query}",
                                                           overall_plan=supervisor_list[-1]["unknown_supervisor"]["plan_checklist"],
                                                           history_sum=history_sum_content)
    FLOCK_NODES.append(llm_node)

    end_node = EndStep()
    end_node.position["x"], end_node.position["y"] = 250, position_y
    FLOCK_NODES.append(end_node)



    flock = Flock()
    for n in FLOCK_NODES:
        flock.config["nodes"].append(
            {
                "id": n.id,
                "type": n.type,
                "position": n.position,
                "data": n.data
            }
        )
    for i in range(len(FLOCK_NODES)-1):
        flock.config["edges"].append(
            {
                "id": f"reactflow__edge-{FLOCK_NODES[i].id}right-{FLOCK_NODES[i+1].id}left",  # 边的id
                "source": FLOCK_NODES[i].id,
                "target": FLOCK_NODES[i+1].id,
                "sourceHandle": "right",
                "targetHandle": "left",
                "type": "default"
            }
        )
    flock.config["metadata"]["start_connections"].append({"target": FLOCK_NODES[1].id, "type": "default"})
    flock.config["metadata"]["end_connections"].append({"source": FLOCK_NODES[-2].id, "type": "default"})
    flock.config["metadata"]["entry_point"] = FLOCK_NODES[1].id

    flock_output = {"name":flock.name, "description":flock.description,
                    "config":flock.config, "updated_at":flock.updated_at}
    return flock_output


# # 假设结果存在文件 case_test.jsonl中
# # d = load_formatted_json("case_test.jsonl")
# with jsonlines.open("case_test.jsonl") as f:
#     # 逐行读取文件
#     for line in f:
#         # 移除行尾的换行符并解析 JSON
#         print(type(line))
#         # print(line)
#         # json_object = json.loads(line)
#         f = format_trace_to_flock(line)
#         print(json.dumps(f,indent=2,ensure_ascii=False))