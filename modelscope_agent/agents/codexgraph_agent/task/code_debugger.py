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
        return response

    def dispatch_function_call(self, callinfo: dict) -> str:
        """
        根据LLM返回的function name和参数，调用本地同名函数，生成Cypher。
        """
        name = callinfo.get("name")
        arguments = callinfo.get("arguments", {})
        func = getattr(self, name, None)
        if func:
            return func(**arguments)
        return ""
    # ---- end reusable functions ----

    def find_nodes_in_file(self, keyword):
        # 通用查询，适用于 C/其他语言的 file_path 属性
        return f"MATCH (n) WHERE n.file_path CONTAINS '{keyword}' RETURN labels(n) AS node_type, n.name, n.file_path, n"

    def find_references(self, keyword):
        # 查找与目标实体有引用/调用关系的节点，兼容 CALL/USES 等关系名
        return (
            f"MATCH (t) WHERE t.name CONTAINS '{keyword}' \n"
            "MATCH (a)-[r]->(t) RETURN labels(a) AS from_labels, a.name AS from_name, type(r) AS rel, labels(t) AS to_labels, t.name AS to_name, t.file_path AS to_file"
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
            response_text = self.llm_call(messages)
            messages.append({'role': 'assistant', 'content': response_text})

            extracted_analysis, _ = extract_text_between_markers(
                response_text, '[start_of_analysis]', '[end_of_analysis]')
            extracted_code_search, _ = extract_text_between_markers(
                response_text, '[start_of_code_search]',
                '[end_of_code_search]')
            extracted_bug_location, _ = extract_text_between_markers(
                response_text, '[start_of_bug_locations]',
                '[end_of_bug_locations]')

            self.update_agent_message(
                response_to_msg(extracted_analysis, extracted_code_search,
                                extracted_bug_location))

            if not extracted_code_search and not extracted_bug_location:
                msg = (
                    'The text between the markers [start_of_code_search] and [end_of_code_search], '
                    'as well as the text between the markers [start_of_bug_locations] '
                    'and [end_of_bug_locations], is empty.')
                messages.append({'role': 'user', 'content': msg})
                continue
            elif extracted_code_search:
                cypher_queries = self.cypher_queries_template.substitute(
                    text_queries=extracted_code_search)
                user_response = self.cypher_agent.run(
                    cypher_queries, retries=self.max_iterations_cypher)

                if not user_response:
                    msg = (
                        'Cypher Code Assistant encountered issues while processing Cypher queries. '
                        'Please try writing simpler and clearer text queries, and ensure '
                        'that the corresponding parameters are correct.')
                    messages.append({'role': 'user', 'content': msg})
                else:
                    messages.append({'role': 'user', 'content': user_response})
                    self.update_user_message(user_response)

            elif extracted_bug_location:
                cypher_queries = self.cypher_queries_buggy_template.substitute(
                    text_queries=extracted_code_search)
                user_response = self.cypher_agent.run(
                    cypher_queries, retries=self.max_iterations_cypher)

                if not user_response:
                    msg = (
                        'Cypher Code Assistant encountered issues while processing Cypher queries. '
                        'Please try writing simpler and clearer text queries, and ensure that the '
                        'corresponding parameters are correct.')
                    messages.append({'role': 'user', 'content': msg})
                    continue

                collated_tool_response = f'Here is the code in buggy locations:\n\n{user_response}'

                if 'Node' not in user_response:
                    collated_tool_response += (
                        '\n\nIt seems that buggy locations are missing. '
                        'Please try again.')
                    messages.append({
                        'role': 'user',
                        'content': collated_tool_response
                    })
                    continue

                messages.append({
                    'role': 'user',
                    'content': collated_tool_response
                })
                self.update_user_message(collated_tool_response)
                break

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
