from copy import deepcopy

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

    def function_call_llm(self, user_query: str):
        """
        让LLM根据所有function schema自动选择function并给出参数。
        返回结构化function调用信息：{"name":..., "arguments":{...}}
        """
        tools = [func['name'] for func in self.FUNCTIONS]
        tools_repr = ', '.join(tools)
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
        import json
        if isinstance(response, str):
            try:
                response = json.loads(response)
            except Exception:
                pass
        # 可视化工具选择过程：把 LLM 的原始输出和解析后结果发送到 agent 消息流
        try:
            raw = response if not isinstance(response, dict) else str(response)
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

    def _run(self, user_query: str, file_path: str = '', **kwargs) -> str:

        self.chat_history = []

        # 先尝试让 LLM 在可用 FUNCTIONS 中选择一个工具（最小化复用 code_chat 的行为）
        callinfo = None
        try:
            callinfo = self.function_call_llm(user_query)
        except Exception:
            callinfo = None

        if callinfo and isinstance(callinfo, dict) and 'name' in callinfo:
            # 分发到本地function，生成Cypher并执行（同步返回结果）
            cypher_query = self.dispatch_function_call(callinfo)
            if cypher_query:
                user_response = self.cypher_agent.run(
                    cypher_query, retries=self.max_iterations_cypher)
                # 将查询结果作为最终输出的基础（debugger 的 _run 期望返回 string）
                # 这里保留原有 debugger 的分析流程较短，直接返回节点信息并尝试让 LLM 汇总
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

                # 输出工具返回的原始结果到 agent 消息流，便于追踪
                try:
                    self.update_agent_message(f"[Tool result] {str(user_response)[:2000]}")
                except Exception:
                    logger.debug("Tool result: %s", user_response)

                # 请求 LLM 基于查询结果给出简要分析
                try:
                    analysis = self.llm_call([{'role': 'user', 'content': f'请基于以下查询结果做简明中文分析：\n{node_info}'}])
                except Exception:
                    analysis = ''

                return f"{node_info}\n【自动分析总结】\n{analysis}"

        primary_user_prompt = self.primary_user_prompt_template.substitute()

        if file_path:
            file_path = f'`file_path`: `{file_path}`\n'

        user_query_issue = f'<issue>\n{file_path}{user_query}\n<\\issue>\n'

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
            response = self.llm_call(messages)
            import json
            # 尝试把 LLM 输出解析为 JSON，如果是字符串形式的 JSON 列表/字典，则转换
            if isinstance(response, str):
                try:
                    response = json.loads(response)
                except Exception:
                    pass

            # 支持单调用或多调用计划（LLM 可能返回列表）
            if callinfo:
                calls_list = []
                if isinstance(callinfo, list):
                    calls_list = callinfo
                elif isinstance(callinfo, dict) and 'name' in callinfo:
                    calls_list = [callinfo]

                if calls_list:
                    aggregated_results = []
                    # 按序执行每个工具调用
                    for idx, single_call in enumerate(calls_list, start=1):
                        try:
                            self.update_agent_message(f"[Dispatch] calling function '{single_call.get('name')}' with arguments: {single_call.get('arguments')}")
                        except Exception:
                            logger.debug("Dispatch message failed for %s", single_call)

                        cypher_query = self.dispatch_function_call(single_call)
                        if not cypher_query:
                            aggregated_results.append({'call': single_call, 'result': None, 'error': 'no cypher generated'})
                            continue

                        try:
                            user_response = self.cypher_agent.run(cypher_query, retries=self.max_iterations_cypher)
                        except Exception as e:
                            logger.exception("cypher_agent.run failed")
                            aggregated_results.append({'call': single_call, 'result': None, 'error': str(e)})
                            continue

                        # 尝试将结果标准化并记录
                        aggregated_results.append({'call': single_call, 'result': user_response})

                        # 把每个工具返回可视化
                        try:
                            self.update_agent_message(f"[Tool result #{idx}] {str(user_response)[:2000]}")
                            # 也把部分结果放到用户消息区，便于 UI 立刻可见
                            self.update_user_message(str(user_response)[:2000])
                        except Exception:
                            logger.debug("Failed to push tool result to UI")

                    # 将聚合结果格式化为 node_info，交给 LLM 做统一分析
                    node_info = "\n【聚合工具调用结果】\n"
                    for entry in aggregated_results:
                        call = entry.get('call')
                        res = entry.get('result')
                        err = entry.get('error')
                        node_info += f"- call: {call.get('name')} args={call.get('arguments')}\n"
                        if err:
                            node_info += f"  error: {err}\n"
                        else:
                            node_info += f"  result: {str(res)[:1000]}\n"

                    try:
                        analysis = self.llm_call([{'role': 'user', 'content': f'请基于以下查询结果做简明中文分析：\n{node_info}'}])
                    except Exception:
                        analysis = ''

                    return f"{node_info}\n【自动分析总结】\n{analysis}"                

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

    def generate(self, messages):
        messages = deepcopy(messages)
        messages = replace_system_prompt(messages, SYSTEM_PROMPT)
        response_text = self.llm_call(messages)
        return response_text
