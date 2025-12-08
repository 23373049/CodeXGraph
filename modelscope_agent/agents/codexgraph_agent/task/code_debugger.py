from copy import deepcopy
import json
import re

from modelscope_agent.agents.codexgraph_agent.cypher_agent import \
    CODE_SEARCH_FORMAT
from modelscope_agent.agents.codexgraph_agent.task.code_general import \
    CodexGraphAgentGeneral
from modelscope_agent.agents.codexgraph_agent.utils.code_utils import \
    extract_text_between_markers
from modelscope_agent.agents.codexgraph_agent.utils.prompt_utils import (
    load_prompt_template, replace_system_prompt)
from modelscope_agent.environment.graph_database import GraphDatabaseHandler
import logging

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are a software developer maintaining a large project.
You are working on an issue submitted to your project.
The issue contains a description marked between <issue> and </issue>.
You ultimate goal is to write a patch that resolves this issue.
"""

BUG_LOCALIZATION_FORMAT = """[start_of_bug_locations]
### Text Description 1 for Bug Location
- Concise text description for the bug location: <text_description_of_the_buggy_location>
- Why: <the_reason_why_it_is_buggy>

### Text Description 2 for Bug Location
- Concise text description for the bug location: <text_description_of_the_buggy_location>
- Why: <the_reason_why_it_is_buggy>
...
### Text Description n for Bug Location
- Concise text description for the bug location: <text_description_of_the_buggy_location>
- Why: <the_reason_why_it_is_buggy>
[end_of_bug_locations]
"""


def response_to_msg(extraced_analysis, extraced_code_search,
                    extraced_bug_location):
    msg = ''
    if extraced_analysis:
        msg += f'## analysis\n\n{extraced_analysis}\n\n'
    if extraced_code_search:
        msg += f'## code_search\n\n{extraced_code_search}\n\n'
    if extraced_bug_location:
        msg += f'## bug_location\n\n{extraced_bug_location}\n\n'
    return msg


def markdown_answer(answer):
    # <file>...</file>
    # <original>...</original>
    # <patched>...</patched>
    answer = answer.replace('```', '')
    replace_dict = {
        '<file>': '\n```text\n',
        '</file>': '\n```\n',
        '<original>': '\n## Original: \n```python\n',
        '</original>': '\n```\n',
        '<patched>': '\n## Patched: \n```python\n',
        '</patched>': '\n```\n',
    }
    for key, value in replace_dict.items():
        answer = answer.replace(key, value)
    return answer


class CodexGraphAgentDebugger(CodexGraphAgentGeneral):

    def __init__(self,
                 llm,
                 prompt_path: str,
                 schema_path: str,
                 task_id: str,
                 graph_db: GraphDatabaseHandler,
                 max_iterations=5,
                 max_iterations_cypher=5,
                 language: str = 'python',
                 message_callback=None):
        super().__init__(
            llm=llm,
            prompt_path=prompt_path,
            schema_path=schema_path,
            task_id=task_id,
            graph_db=graph_db,
            max_iterations=max_iterations,
            max_iterations_cypher=max_iterations_cypher,
            language=language,
            message_callback=message_callback)

        self.cypher_queries_buggy_template = load_prompt_template(
            prompt_path, 'start_prompt_cypher_buggy_loc.txt')

    def set_action_type_and_message(self):
        pass

    def _label_map(self):
        """返回当前 agent 语言对应的标签映射，兼容 C 与 Python 风格标签。"""
        lang = (getattr(self, 'language', '') or '').lower()
        if lang.startswith('c'):
            return {
                'class_label': 'STRUCT',
                'module_label': 'FILE',
                'method_label': 'FUNCTION',
                'field_label': 'STRUCT_MEMBER',
                'function_label': 'FUNCTION'
            }
        # 默认 python 风格
        return {
            'class_label': 'CLASS',
            'module_label': 'MODULE',
            'method_label': 'FUNCTION',
            'field_label': 'FIELD',
            'function_label': 'FUNCTION'
        }

    FUNCTIONS = [
        {
            "name": "find_nodes_in_file",
            "description": (
                "查找某个文件下的所有节点。"
                "适用于用户提出如：'列出xxx.py的所有节点'、'show all nodes in xxx.py'、'查找文件xxx.py的内容'等问题。"
                "示例：'请列出code_chat.py文件的所有节点' -> keyword='code_chat.py'"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "keyword": {"type": "string", "description": "要查找的文件名或路径，如code_chat.py"}
                },
                "required": ["keyword"]
            }
        },
        {
            "name": "find_class_by_keyword",
            "description": (
                "查找CLASS名称中包含关键词。"
                "适用于用户提出如：'查找包含Agent的类'、'find class with Agent'、'有哪些类名带Agent'等问题。"
                "示例：'查找所有包含Graph的类' -> keyword='Graph'"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "keyword": {"type": "string", "description": "类名关键词，如Agent"}
                },
                "required": ["keyword"]
            }
        },
        {
            "name": "find_function_by_keyword",
            "description": (
                "查找FUNCTION名称中包含关键词。"
                "适用于用户提出如：'查找包含run的函数'、'find function with run'、'有哪些函数名带run'等问题。"
                "示例：'查找所有包含call的函数' -> keyword='call'"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "keyword": {"type": "string", "description": "函数名关键词，如run"}
                },
                "required": ["keyword"]
            }
        },
        {
            "name": "introduce_entity",
            "description": (
                "介绍、讲解、说明、解释、总结代码中的某个实体（如模块、类、函数等）。"
                "适用于用户提出如：'请介绍xxx'、'explain xxx'、'what is xxx'、'summary xxx'、'说明xxx的作用'、'explain code_chat'、'describe xxx'、'讲讲xxx'、'xxx是什么'等问题。"
                "请优先选择本函数用于所有与代码实体讲解、说明、解释、介绍、summary、explain、describe、what is、作用、功能等相关需求。"
                "示例：'请介绍code_chat模块' -> keyword='code_chat'；'explain code_chat' -> keyword='code_chat'"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "keyword": {"type": "string", "description": "要介绍的实体名，如code_chat"}
                },
                "required": ["keyword"]
            }
        },
        {
            "name": "find_references",
            "description": (
                "查找某个实体在代码库中的引用关系，适用于查找函数/类被哪些其他实体调用或引用。"
                "示例：'查找引用 code_chat' -> keyword='code_chat'"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "keyword": {"type": "string", "description": "要查找引用的实体名关键词，如code_chat"}
                },
                "required": ["keyword"]
            }
        },
        {
            "name": "find_call_hierarchy",
            "description": (
                "查找函数/类的调用层级（调用者和被调用者），会返回与目标节点直接相连的上游调用者和下游被调用者，适合回答类似：'谁调用了X'、'X调用了哪些函数'、'给出X的调用层级'。\n"
                "注意：keyword 为实体名关键词，层级默认深度为1..2（可在本地 Cypher 中调整）。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "keyword": {"type": "string", "description": "要查找调用层级的实体名关键词，如process_request"}
                },
                "required": ["keyword"]
            }
        },
    ]

    def function_call_llm(self, user_query: str, allow_multiple: bool = False):
        """
        让LLM根据所有function schema自动选择function并给出参数。
        返回结构化function调用信息：{"name":..., "arguments":{...}} 或列表
        """
        tools = [func['name'] for func in self.FUNCTIONS]
        tools_repr = ', '.join(tools)
        
        if allow_multiple:
            system_content = (
                "严格从下列工具（function）中选择一个或多个调用，不要创造新工具名。\n"
                "可以返回单个 JSON 对象或 JSON 数组。\n"
                "如果返回数组，每个元素必须包含 name 和 arguments 两个键。\n"
                "本地函数中需要的参数均为keyword，所以在arguments中只包含keyword即可。\n"
                "可用工具: " + tools_repr + "。\n"
                "禁止输出任何解释文字或代码块标记。\n"
                "单个工具示例: {\"name\":\"introduce_entity\",\"arguments\":{\"keyword\":\"code_chat\"}}\n"
                "多个工具示例: [{\"name\":\"find_class_by_keyword\",\"arguments\":{\"keyword\":\"Agent\"}},{\"name\":\"find_function_by_keyword\",\"arguments\":{\"keyword\":\"run\"}}]"
            )
        else:
            system_content = (
                "严格从下列工具（function）中选择一个调用，不要创造新工具名。不要输出额外的解释或多余文本。\n"
                "只允许返回一个 JSON，且顶层必须且仅包含两个键：name 和 arguments。\n"
                "本地函数中需要的参数均为keyword，所以在arguments中只包含keyword即可。\n"
                "可用工具: " + tools_repr + "。\n"
                "禁止输出任何解释文字或代码块标记。\n"
                '{"name":"introduce_entity","arguments":{"keyword":"code_chat"}}'
            )
        messages = [
            {"role": "system", "content": system_content},
            {"role": "user", "content": user_query}
        ]
        response = self.llm_call(messages)
        if isinstance(response, str):
            try:
                response = json.loads(response)
            except Exception:
                pass
        # 可视化工具选择过程：把 LLM 的原始输出和解析后结果发送到 agent 消息流
        try:
            raw = response if not isinstance(response, (dict, list)) else str(response)
        except Exception:
            raw = repr(response)
        msg = f"[Tool selection] user_query={user_query} | raw_response={raw}"
        try:
            self.update_agent_message(msg)
        except Exception:
            logger.debug(msg)
        return response

    def dispatch_function_call(self, callinfo: dict) -> str:
        """
        根据LLM返回的function name和参数，调用本地同名函数，生成Cypher。
        """
        name = callinfo.get("name")
        arguments = callinfo.get("arguments", {})
        # 记录分发过程
        try:
            self.update_agent_message(f"[Dispatch] calling function '{name}' with arguments: {arguments}")
        except Exception:
            logger.debug("Dispatch: %s %s", name, arguments)
        func = getattr(self, name, None)
        if func:
            cypher = func(**arguments)
            # 把生成的 Cypher 输出到消息流，便于观察
            try:
                self.update_agent_message(f"[Cypher] {cypher}")
            except Exception:
                logger.debug("Cypher: %s", cypher)
            return cypher
        return ""
    # ---- end reusable functions ----

    def find_nodes_in_file(self, keyword):
        return f"MATCH (n) WHERE n.file_path CONTAINS '{keyword}' RETURN labels(n) AS node_type, n.name, n.file_path, n"

    def find_class_by_keyword(self, keyword):
        labels = self._label_map()
        class_label = labels.get('class_label', 'CLASS')
        return f"MATCH (c:{class_label}) WHERE c.name CONTAINS '{keyword}' RETURN c.name, c.file_path, c.signature, c.code"

    def find_function_by_keyword(self, keyword):
        labels = self._label_map()
        method_label = labels.get('method_label', 'FUNCTION')
        return f"MATCH (f:{method_label}) WHERE f.name CONTAINS '{keyword}' RETURN f.name, f.file_path, f.signature, f.code"

    def introduce_entity(self, keyword):
        return f"MATCH (n) WHERE n.name CONTAINS '{keyword}' RETURN labels(n) AS node_type, n.name, n.file_path, n.code"

    def find_references(self, keyword):
        """查找引用关系：查找与目标实体通过常见引用/调用关系相连的节点，并返回节点与关系信息。"""
        # 匹配 CALLS / USES / DEPENDS_ON 等关系（如果图模型使用不同关系名，需调整）
        return (
            f"MATCH (t) WHERE t.name CONTAINS '{keyword}' \\n"
            "MATCH (a)-[r]->(t) RETURN labels(a) AS from_labels, a.name AS from_name, type(r) AS rel, labels(t) AS to_labels, t.name AS to_name, t.file_path AS to_file"
        )

    def find_call_hierarchy(self, keyword):
        """查找调用层级：返回与目标实体相关的上游调用者（callers）和下游被调用者（callees）。
        默认只展开 1..2 层 CALLS 关系以避免结果爆炸。"""
        # 尝试同时匹配 CALLS 和 USES 两种常见的调用/依赖关系，兼容不同图模型
        # 注意：某些 Cypher 引擎对 [:TYPE1|TYPE2*min..max] 的语法支持可能不同，
        # 若执行报错，可改为分别查询或使用 WHERE type(r) IN [...] 形式。
        return (
            f"MATCH (t) WHERE t.name CONTAINS '{keyword}' "
            "OPTIONAL MATCH (caller)-[r1:CALLS|USES*1..2]->(t) "
            "OPTIONAL MATCH (t)-[r2:CALLS|USES*1..2]->(callee) "
            "RETURN DISTINCT labels(t) AS target_labels, t.name AS target_name, t.file_path AS target_file, "
            "collect(DISTINCT {from_labels: labels(caller), from_name: caller.name, rel: type(r1)}) AS callers, "
            "collect(DISTINCT {to_labels: labels(callee), to_name: callee.name, rel: type(r2)}) AS callees"
        )

    def question_to_cypher(self, question: str) -> str:
        """
        将自然语言的问题转换为一个基础的 Cypher 查询，
        根据当前 agent 的语言（self.language）调整图谱标签映射（例如 C 使用 STRUCT/FILE）。
        """
        kw = question.strip().strip('\"\'')
        # 构造通用的匹配查询：匹配 name 字段包含关键字的任意节点
        cypher = (
            f"MATCH (n) WHERE toLower(coalesce(n.name, '')) CONTAINS toLower('{kw}') "
            "RETURN labels(n) AS node_type, n.name AS name, n.file_path AS file_path, n.signature AS signature, n.code AS code"
        )
        return cypher

    def generate_debug_plan(self, user_query: str, file_path: str = '') -> dict:
        """
        生成 Debug 计划：分析问题并制定结构化的多步骤调试计划。
        返回包含步骤列表的计划字典。
        """
        if file_path:
            issue_context = f'<issue>\n{file_path}{user_query}\n</issue>\n'
        else:
            issue_context = f'<issue>\n{user_query}\n</issue>\n'
        
        plan_prompt = (
            "你是一个经验丰富的软件调试专家。请分析以下 bug 报告，并制定一个结构化的调试计划。\n\n"
            f"{issue_context}\n\n"
            "请按照以下 JSON 格式返回调试计划：\n"
            "{\n"
            '  "analysis": "对问题的简要分析，包括错误类型、可能涉及的模块等",\n'
            '  "steps": [\n'
            '    {\n'
            '      "step_id": 1,\n'
            '      "goal": "这一步的目标是什么",\n'
            '      "tools": ["tool_name1", "tool_name2"],\n'
            '      "tool_args": [{"keyword": "arg1"}, {"keyword": "arg2"}],\n'
            '      "expected_result": "预期得到什么信息",\n'
            '      "depends_on": []\n'
            '    },\n'
            '    {\n'
            '      "step_id": 2,\n'
            '      "goal": "下一步的目标",\n'
            '      "tools": ["tool_name"],\n'
            '      "tool_args": [{"keyword": "arg"}],\n'
            '      "expected_result": "预期结果",\n'
            '      "depends_on": [1]\n'
            '    }\n'
            "  ]\n"
            "}\n\n"
            "可用工具列表: " + ', '.join([func['name'] for func in self.FUNCTIONS]) + "\n"
            "注意：\n"
            "- 每个步骤可以调用一个或多个工具\n"
            "- depends_on 表示该步骤依赖的步骤ID（空数组表示无依赖）\n"
            "- 工具参数统一使用 keyword 字段\n"
            "- 只返回 JSON，不要输出其他文字\n"
        )
        
        try:
            self.update_agent_message("[Debug Plan] 正在生成调试计划...")
            response = self.llm_call([{'role': 'user', 'content': plan_prompt}])
            
            if isinstance(response, str):
                # 尝试提取 JSON
                try:
                    # 移除可能的代码块标记
                    response = response.strip()
                    if response.startswith('```'):
                        lines = response.split('\n')
                        response = '\n'.join(lines[1:-1]) if len(lines) > 2 else response
                    plan = json.loads(response)
                except Exception as e:
                    logger.warning(f"Failed to parse plan JSON: {e}, response: {response[:200]}")
                    # 如果解析失败，创建一个默认计划
                    plan = {
                        "analysis": "自动生成计划失败，将使用默认调试流程",
                        "steps": [{
                            "step_id": 1,
                            "goal": "初步分析问题",
                            "tools": ["introduce_entity"],
                            "tool_args": [{"keyword": user_query.split()[0] if user_query.split() else "main"}],
                            "expected_result": "获取相关代码信息",
                            "depends_on": []
                        }]
                    }
            else:
                plan = response if isinstance(response, dict) else {"analysis": "", "steps": []}
            
            # 验证计划格式
            if not isinstance(plan, dict) or 'steps' not in plan:
                plan = {"analysis": plan.get('analysis', ''), "steps": []}
            
            plan['analysis'] = plan.get('analysis', '')
            plan['steps'] = plan.get('steps', [])
            
            try:
                self.update_agent_message(f"[Debug Plan] 计划生成完成，共 {len(plan['steps'])} 个步骤\n分析: {plan['analysis'][:200]}")
            except Exception:
                logger.debug("Debug plan generated: %d steps", len(plan.get('steps', [])))
            
            return plan
        except Exception as e:
            logger.exception("Failed to generate debug plan")
            # 返回一个简单的默认计划
            return {
                "analysis": f"计划生成出错: {str(e)}",
                "steps": [{
                    "step_id": 1,
                    "goal": "初步探索",
                    "tools": ["introduce_entity"],
                    "tool_args": [{"keyword": "main"}],
                    "expected_result": "获取基本信息",
                    "depends_on": []
                }]
            }

    def execute_plan_step(self, step: dict, collected_results: list) -> dict:
        """
        执行计划中的一个步骤，返回执行结果。
        """
        step_id = step.get('step_id', 0)
        tools = step.get('tools', [])
        tool_args = step.get('tool_args', [])
        goal = step.get('goal', '')
        
        try:
            self.update_agent_message(f"[Step {step_id}] 目标: {goal}")
        except Exception:
            logger.debug("Step %d: %s", step_id, goal)
        
        step_results = []
        
        # 执行该步骤中的所有工具调用
        # 确保 tools 和 tool_args 长度匹配
        min_len = min(len(tools), len(tool_args)) if tool_args else len(tools)
        for idx in range(min_len):
            tool_name = tools[idx]
            tool_arg = tool_args[idx] if idx < len(tool_args) else {}
            
            if tool_name not in [f['name'] for f in self.FUNCTIONS]:
                logger.warning(f"Unknown tool: {tool_name}")
                step_results.append({
                    'tool': tool_name,
                    'result': None,
                    'error': f'Unknown tool: {tool_name}'
                })
                continue
            
            try:
                self.update_agent_message(f"[Step {step_id}.{idx+1}] 调用工具: {tool_name} with {tool_arg}")
            except Exception:
                logger.debug("Step %d.%d: %s %s", step_id, idx+1, tool_name, tool_arg)
            
            callinfo = {"name": tool_name, "arguments": tool_arg}
            cypher_query = self.dispatch_function_call(callinfo)
            
            if not cypher_query:
                step_results.append({
                    'tool': tool_name,
                    'result': None,
                    'error': 'no cypher generated'
                })
                continue
            
            try:
                query_result = self.cypher_agent.run(cypher_query, retries=self.max_iterations_cypher)
                step_results.append({
                    'tool': tool_name,
                    'result': query_result,
                    'error': None
                })
                
                # 可视化结果
                try:
                    result_str = str(query_result)[:1000]
                    self.update_agent_message(f"[Step {step_id}.{idx+1} Result] {result_str}")
                except Exception:
                    logger.debug("Step %d.%d result: %s", step_id, idx+1, str(query_result)[:200])
            except Exception as e:
                logger.exception(f"Tool execution failed: {tool_name}")
                step_results.append({
                    'tool': tool_name,
                    'result': None,
                    'error': str(e)
                })
        
        return {
            'step_id': step_id,
            'goal': goal,
            'results': step_results,
            'success': any(r.get('result') is not None and r.get('error') is None for r in step_results)
        }

    def validate_and_adjust_plan(self, plan: dict, execution_results: list) -> dict:
        """
        验证执行结果，判断是否需要调整计划。
        返回调整后的计划（如果需要）。
        """
        # 检查是否有步骤失败
        failed_steps = [r for r in execution_results if not r.get('success', False)]
        
        if not failed_steps:
            # 所有步骤都成功，检查是否收集到足够信息
            all_results = []
            for exec_result in execution_results:
                for tool_result in exec_result.get('results', []):
                    if tool_result.get('result'):
                        all_results.append(tool_result['result'])
            
            # 简单检查：如果结果为空或太少，可能需要补充步骤
            if len(all_results) == 0 or all([not r or (isinstance(r, list) and len(r) == 0) for r in all_results]):
                try:
                    self.update_agent_message("[Plan Adjustment] 结果不足，考虑添加补充查询步骤")
                except Exception:
                    logger.debug("Results insufficient, may need additional steps")
                # 这里可以添加新的步骤，但为了简化，暂时不自动添加
                return plan
        
        # 如果有失败的步骤，可以考虑调整
        if failed_steps:
            try:
                self.update_agent_message(f"[Plan Adjustment] 检测到 {len(failed_steps)} 个步骤执行失败")
            except Exception:
                logger.debug("%d steps failed", len(failed_steps))
        
        return plan

    def locate_bug(self, plan: dict, execution_results: list) -> str:
        """
        基于收集的信息进行综合分析，定位疑似 bug。
        返回 bug 定位结果。
        """
        # 汇总所有收集的信息
        collected_info = "\n【调试过程汇总】\n"
        collected_info += f"问题分析: {plan.get('analysis', '')}\n\n"
        
        collected_info += "【执行步骤与结果】\n"
        for exec_result in execution_results:
            step_id = exec_result.get('step_id', 0)
            goal = exec_result.get('goal', '')
            collected_info += f"\n步骤 {step_id}: {goal}\n"
            
            for tool_result in exec_result.get('results', []):
                tool_name = tool_result.get('tool', '')
                result = tool_result.get('result')
                error = tool_result.get('error')
                
                if error:
                    collected_info += f"  - {tool_name}: 执行失败 - {error}\n"
                elif result:
                    if isinstance(result, list):
                        collected_info += f"  - {tool_name}: 找到 {len(result)} 个结果\n"
                        # 显示前几个结果的详细信息，包括代码片段
                        for i, item in enumerate(result[:5]):  # 增加到5个结果
                            if isinstance(item, dict):
                                name = item.get('name', item.get('from_name', ''))
                                file_path = item.get('file_path', '')
                                signature = item.get('signature', '')
                                code = item.get('code', '')
                                collected_info += f"    [{i+1}] {name} ({file_path})\n"
                                if signature:
                                    collected_info += f"        签名: {signature}\n"
                                if code:
                                    # 显示代码的前200字符作为预览
                                    code_preview = code[:200].replace('\n', ' ')
                                    collected_info += f"        代码预览: {code_preview}...\n"
                    else:
                        collected_info += f"  - {tool_name}: {str(result)[:200]}\n"
        
        # 让 LLM 基于收集的信息进行 bug 定位分析
        localization_prompt = (
            "基于以下调试过程收集的信息，请分析并定位可能的 bug 位置。\n\n"
            f"{collected_info}\n\n"
            "请按照以下格式输出 bug 定位结果：\n"
            f"{BUG_LOCALIZATION_FORMAT}\n\n"
            "注意：\n"
            "- 如果信息不足，可以说明还需要哪些信息\n"
            "- 如果已经定位到 bug，请明确指出位置和原因\n"
            "- 必须明确指出具体的函数名、类名、文件路径等，以便后续使用实际查询到的代码\n"
            "- 可以标记多个疑似位置，按可能性排序\n"
            "- 在描述bug位置时，请引用上面查询结果中出现的具体节点名称和文件路径\n"
        )
        
        try:
            self.update_agent_message("[Bug Localization] 正在分析并定位 bug...")
            localization_result = self.llm_call([{'role': 'user', 'content': localization_prompt}])
            return localization_result
        except Exception as e:
            logger.exception("Bug localization failed")
            return f"Bug 定位分析失败: {str(e)}\n\n{collected_info}"

    def _run(self, user_query: str, file_path: str = '', **kwargs) -> str:
        """
        改进后的调试流程：
        1. 生成 Debug 计划
        2. 按计划执行工具调用
        3. 验证结果并调整计划（如需要）
        4. Bug 定位
        5. 生成修复方案
        """
        self.chat_history = []

        # 格式化文件路径
        file_path_str = f'`file_path`: `{file_path}`\n' if file_path else ''

        # 阶段1: 生成 Debug 计划
        try:
            debug_plan = self.generate_debug_plan(user_query, file_path_str)
        except Exception as e:
            logger.exception("Failed to generate debug plan, falling back to simple flow")
            # 如果计划生成失败，回退到简单流程
            return self._run_simple_flow(user_query, file_path_str)

        if not debug_plan.get('steps'):
            logger.warning("Empty debug plan, falling back to simple flow")
            return self._run_simple_flow(user_query, file_path_str)

        # 阶段2: 执行计划
        execution_results = []
        executed_step_ids = set()
        
        # 按依赖关系排序执行步骤
        steps = debug_plan.get('steps', [])
        remaining_steps = {step['step_id']: step for step in steps}
        
        max_plan_iterations = len(steps) * 2  # 防止无限循环
        iteration = 0
        
        while remaining_steps and iteration < max_plan_iterations:
            iteration += 1
            # 找到可以执行的步骤（依赖已满足或没有依赖）
            ready_steps = [
                step for step in remaining_steps.values()
                if not step.get('depends_on') or all(dep_id in executed_step_ids for dep_id in step.get('depends_on', []))
            ]
            
            if not ready_steps:
                # 如果没有可执行的步骤，可能是依赖关系有问题，尝试执行所有剩余步骤
                ready_steps = list(remaining_steps.values())
            
            # 执行所有就绪的步骤
            for step in ready_steps:
                step_result = self.execute_plan_step(step, execution_results)
                execution_results.append(step_result)
                executed_step_ids.add(step['step_id'])
                remaining_steps.pop(step['step_id'], None)
        
        # 阶段3: 验证结果并调整计划（如果需要）
        adjusted_plan = self.validate_and_adjust_plan(debug_plan, execution_results)
        
        # 阶段4: Bug 定位
        try:
            bug_location = self.locate_bug(adjusted_plan, execution_results)
        except Exception as e:
            logger.exception("Bug localization failed")
            bug_location = f"Bug 定位过程出错: {str(e)}"

        # 阶段5: 生成修复方案
        try:
            fix_solution = self.generate_fix_solution(user_query, file_path_str, debug_plan, execution_results, bug_location)
        except Exception as e:
            logger.exception("Fix solution generation failed")
            fix_solution = f"修复方案生成失败: {str(e)}"

        # 整合所有结果
        final_result = self._format_final_result(debug_plan, execution_results, bug_location, fix_solution)
        
        try:
            self.update_agent_message(final_result)
        except Exception:
            logger.debug("Final result generated")
        
        return final_result

    def _run_simple_flow(self, user_query: str, file_path: str = '') -> str:
        """
        简单的回退流程：当计划生成失败时使用。
        保持原有逻辑以兼容性。
        """
        # 先尝试让 LLM 在可用 FUNCTIONS 中选择一个工具
        callinfo = None
        try:
            callinfo = self.function_call_llm(user_query)
        except Exception:
            callinfo = None

        if callinfo and isinstance(callinfo, dict) and 'name' in callinfo:
            # 分发到本地function，生成Cypher并执行
            cypher_query = self.dispatch_function_call(callinfo)
            if cypher_query:
                try:
                    user_response = self.cypher_agent.run(
                        cypher_query, retries=self.max_iterations_cypher)
                    node_info = "\n【节点详细信息】\n"
                    if isinstance(user_response, list):
                        for node in user_response:
                            node_info += (
                                f"类型: {node.get('node_type', '')}\n"
                                f"名称: {node.get('name', '')}\n"
                                f"路径: {node.get('file_path', '')}\n"
                                f"签名: {node.get('signature', '')}\n"
                                f"代码: {node.get('code', '')}\n\n"
                            )
                    else:
                        node_info += str(user_response)

                    try:
                        self.update_agent_message(f"[Tool result] {str(user_response)[:2000]}")
                    except Exception:
                        logger.debug("Tool result: %s", user_response)

                    try:
                        analysis = self.llm_call([{'role': 'user', 'content': f'请基于以下查询结果做简明中文分析：\n{node_info}'}])
                    except Exception:
                        analysis = ''

                    return f"{node_info}\n【自动分析总结】\n{analysis}"
                except Exception as e:
                    logger.exception("Simple flow execution failed")
                    return f"执行失败: {str(e)}"

        # 使用原有的迭代流程
        primary_user_prompt = self.primary_user_prompt_template.substitute()

        user_query_issue = f'<issue>\n{file_path}{user_query}\n</issue>\n'

        messages = [
            {
                'role': 'system',
                'content': self.system_prompts
            },
            {
                'role': 'user',
                'content': user_query_issue
            },
            {
                'role': 'user',
                'content': primary_user_prompt
            },
        ]

        self.chat_history.append(('system', self.system_prompts))

        for iter in range(self.max_iterations):
            msg = "Let's analyze collected context first."
            messages.append({'role': 'user', 'content': msg})
            self.update_user_message(msg)

            response_text = self.llm_call(messages)
            messages.append({'role': 'assistant', 'content': response_text})
            self.update_agent_message(response_text)

            if iter < self.max_iterations - 1:
                msg = (
                    'Summarize your analysis first, and tell whether the current context is sufficient, '
                    'write your summarization here: \n#### Concise Summarization:\n...\n'
                    "\nThen if it's sufficient, please continue answering in the following format:\n"
                    f'{CODE_SEARCH_FORMAT}'
                    "\nIf it's not sufficient, please continue answering in the following format:\n"
                    f'{BUG_LOCALIZATION_FORMAT}'
                    '\n\nNOTE:'
                    '\n- If you have already identified the bug locations, do not write any search text queries.'
                    "\n- If you haven't yet reviewed the specific code related to the bug or "
                    'pinpointed the exact location of the bug '
                    '(such as which module, class, method, or function), it is not recommended '
                    'to provide answers that directly specify '
                    'the bug locations.')
                messages.append({'role': 'user', 'content': msg})

        generate_queries = self.generate_queries_template.substitute()
        messages.append({'role': 'user', 'content': generate_queries})

        answer = self.generate(messages)
        answer = markdown_answer(answer)
        self.update_agent_message(answer)
        return answer

    def generate_fix_solution(self, user_query: str, file_path: str, plan: dict, 
                              execution_results: list, bug_location: str) -> str:
        """
        基于收集的信息和 bug 定位结果，生成修复方案。
        """
        # 简化为原来的行为：将 cypher_agent.run() 的原始返回结果（文本或序列化结果）
        # 直接作为用户消息追加到要发送给 LLM 的 messages 中，恢复原样注入流程。
        try:
            self.update_agent_message("[Fix Solution] 将 Cypher 返回原样注入到 LLM 消息中以生成修复方案...")
        except Exception:
            logger.debug("Injecting raw cypher results into messages for fix solution")

        # 构造基础 messages（包含 system prompt 和简短上下文）
        messages = [
            {
                'role': 'system',
                'content': self.system_prompts
            },
            {
                'role': 'user',
                'content': f"问题描述: {user_query}\n\n问题分析: {plan.get('analysis', '')}\n\nBug 定位结果:\n{bug_location}\n\n"
            }
        ]

        # 把 execution_results 中每个工具的原始 result（不做结构化抽取）作为用户消息追加
        for exec_result in execution_results:
            for tool_result in exec_result.get('results', []):
                if tool_result.get('result') and not tool_result.get('error'):
                    try:
                        raw = tool_result.get('result')
                        # 如果是列表或 dict，把它序列化为字符串，保持原样信息
                        if not isinstance(raw, str):
                            try:
                                raw = json.dumps(raw, ensure_ascii=False, default=str)
                            except Exception:
                                raw = str(raw)

                        content = f"[Tool: {tool_result.get('tool')}]\n{raw}"
                        messages.append({'role': 'user', 'content': content})
                        try:
                            self.update_user_message(content)
                        except Exception:
                            logger.debug("Appended tool result to messages: %s", str(content)[:200])
                    except Exception:
                        logger.exception("Failed to append raw tool result to messages")

        # 附加生成 queries 模板（若有）
        try:
            generate_queries = self.generate_queries_template.substitute()
            messages.append({'role': 'user', 'content': generate_queries})
        except Exception:
            pass

        # 在调用大模型前，把将要发送的 messages 内容输出到前端，便于调试和审查
        try:
            try:
                msgs_preview = json.dumps(messages, ensure_ascii=False, default=str)
            except Exception:
                msgs_preview = str(messages)
            # 截断以避免过长输出到前端，但保留尽可能多的信息
            try:
                self.update_agent_message(f"[Messages to LLM]\n{msgs_preview}")
            except Exception:
                logger.debug("Messages to LLM: %s", msgs_preview[:2000])
        except Exception:
            logger.exception("Failed to serialize messages for frontend display")

        try:
            fix_solution = self.generate(messages)
            return fix_solution
        except Exception as e:
            logger.exception("Fix solution generation failed")
            return f"修复方案生成失败: {str(e)}"

    def _format_final_result(self, plan: dict, execution_results: list, 
                             bug_location: str, fix_solution: str) -> str:
        """
        格式化最终输出结果。
        """
        result = "## Debug 调试报告\n\n"
        
        # 1. 问题分析
        result += "### 1. 问题分析\n\n"
        result += f"{plan.get('analysis', '无分析')}\n\n"
        
        # 2. 调试计划
        result += "### 2. 调试计划\n\n"
        for step in plan.get('steps', []):
            result += f"**步骤 {step.get('step_id', 0)}**: {step.get('goal', '')}\n"
            result += f"- 工具: {', '.join(step.get('tools', []))}\n"
            result += f"- 预期结果: {step.get('expected_result', '')}\n\n"
        
        # 3. 执行结果摘要
        result += "### 3. 执行结果摘要\n\n"
        for exec_result in execution_results:
            step_id = exec_result.get('step_id', 0)
            success = exec_result.get('success', False)
            result += f"步骤 {step_id}: {'✓ 成功' if success else '✗ 失败'}\n"
            for tool_result in exec_result.get('results', []):
                tool_name = tool_result.get('tool', '')
                if tool_result.get('error'):
                    result += f"  - {tool_name}: 错误 - {tool_result.get('error')}\n"
                elif tool_result.get('result'):
                    result_count = len(tool_result.get('result')) if isinstance(tool_result.get('result'), list) else 1
                    result += f"  - {tool_name}: 找到 {result_count} 个结果\n"
        result += "\n"
        
        # 4. Bug 定位
        result += "### 4. Bug 定位\n\n"
        result += f"{bug_location}\n\n"
        
        # 5. 修复方案
        result += "### 5. 修复方案\n\n"
        fix_formatted = markdown_answer(fix_solution)
        result += f"{fix_formatted}\n"
        
        return result

    def generate(self, messages):
        messages = deepcopy(messages)
        messages = replace_system_prompt(messages, SYSTEM_PROMPT)
        response_text = self.llm_call(messages)
        return response_text
