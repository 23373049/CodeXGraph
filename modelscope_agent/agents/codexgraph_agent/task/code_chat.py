from copy import deepcopy

from modelscope_agent.agents.codexgraph_agent.cypher_agent import \
    CODE_SEARCH_FORMAT
from modelscope_agent.agents.codexgraph_agent.task.code_general import \
    CodexGraphAgentGeneral
from modelscope_agent.agents.codexgraph_agent.utils.code_utils import \
    extract_text_between_markers
from modelscope_agent.agents.codexgraph_agent.utils.prompt_utils import \
    replace_system_prompt

SYSTEM_PROMPT = (
    'You are a software developer maintaining a large project.\n'
    'Your task is to answer various questions related to the code project raised by users, '
    'which may include asking questions, '
    'fixing bugs, adding function comments, adding new requirements, etc.\n'
    'The issue contains a description marked between <issue> and </issue>.\n')

ANSWER_FORMAT = """[start_of_answer]
### Answer
- Analysis: <analysis of this question>
- Conclusion: <conclusion of this question>
- Source code reference: <reference of Source code>
[end_of_answer]
"""


def response_to_msg(extraced_analysis, extraced_code_search, answer_question):
    msg = ''
    if extraced_analysis:
        msg += f'## analysis\n\n{extraced_analysis}\n\n'
    if extraced_code_search:
        msg += f'## code_search\n\n{extraced_code_search}\n\n'
    if answer_question:
        msg += f'## answer_question\n\n{answer_question}\n\n'
    return msg


def markdown_answer(answer):
    # <file>...</file>
    # <original>...</original>
    # <patched>...</patched>
    answer = answer.replace('```', '')
    replace_dict = {
        '<analysis>': '\n## analysis: \n',
        '</analysis>': '\n',
        '<answer>': '\n## answer: \n',
        '</answer>': '\n',
        '<reference>': '\n## reference: \n',
        '</reference>': '\n',
    }
    for key, value in replace_dict.items():
        answer = answer.replace(key, value)
    return answer



import re

class CodexGraphAgentChat(CodexGraphAgentGeneral):

    def set_action_type_and_message(self):
        pass


    # 1. 定义多个function schema
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

    # 2. 本地实现每个function，返回Cypher
    def find_nodes_in_file(self, keyword):
        return f"MATCH (n) WHERE n.file_path CONTAINS '{keyword}' RETURN labels(n) AS node_type, n.name, n.file_path, n"

    def _label_map(self):
        """返回当前 agent 语言对应的标签映射。"""
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

    def find_class_by_keyword(self, keyword):
        labels = self._label_map()
        class_label = labels.get('class_label', 'CLASS')
        return f"MATCH (c:{class_label}) WHERE c.name CONTAINS '{keyword}' RETURN c.name, c.file_path, c.signature, c.code"

    def find_function_by_keyword(self, keyword):
        labels = self._label_map()
        method_label = labels.get('method_label', 'FUNCTION')
        return f"MATCH (f:{method_label}) WHERE f.name CONTAINS '{keyword}' RETURN f.name, f.file_path, f.signature, f.code"

    def introduce_entity(self, keyword):
        return f"MATCH (n) WHERE n.name CONTAINS '{keyword}' RETURN labels(n) AS node_type, n.name, n.file_path, n"

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
    # 3. LLM调用时传入所有function schema
    def function_call_llm(self, user_query: str):
        """
        让LLM根据所有function schema自动选择function并给出参数。
        返回结构化function调用信息：{"name":..., "arguments":{...}}
        """
        messages = [
            {"role": "system", "content": (
                "严格从下列工具（function）中选择一个调用，不要创造新工具名。"
                "只允许返回一个 JSON，且顶层必须且仅包含两个键：name 和 arguments。\n"
                "本地函数中需要的参数均为keyword，所以在arguments中只包含keyword即可，防止用户输入参数时带入其他参数导致错误。\n"
                f"可用工具: {[func['name'] for func in self.FUNCTIONS]}。\n"
                "禁止输出任何解释文字或代码块标记，不允许使用 function、parameters、function_call 等其他键。\n"
                "示例：{\"name\":\"introduce_entity\",\"arguments\":{\"keyword\":\"code_chat\"}}"
            )},
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


    # 4. 分发到本地function，生成Cypher
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

    def question_to_cypher(self, question: str) -> str:
        """
        将自然语言的问题转换为一个基础的 Cypher 查询，
        根据当前 agent 的语言（self.language）调整图谱中使用的标签名称。

        目标：把针对 Python 的查询适配为针对 C 语言的查询（例如将 CLASS -> STRUCT, MODULE -> FILE 等）。

        返回一个简单的匹配节点的 Cypher 字符串，优先匹配 name 字段包含关键字的节点，并返回常用字段。
        """
        kw = question.strip().strip('\"\'')
        lang = (getattr(self, 'language', '') or '').lower()

        # 默认 Python 风格标签
        class_label = 'CLASS'
        module_label = 'MODULE'
        method_label = 'FUNCTION'
        field_label = 'FIELD'

        # 针对 C 语言的图谱映射（根据用户提供的建议）
        if lang.startswith('c'):
            class_label = 'STRUCT'
            module_label = 'FILE'
            # C 中没有方法/类方法，使用 FUNCTION 表示全局函数
            method_label = 'FUNCTION'
            # 结构体成员
            field_label = 'STRUCT_MEMBER'

        # 构造通用的匹配查询：匹配 name 中包含关键词的任意节点
        # 同时返回节点标签、名称、文件路径、签名和代码（若存在）
        cypher = (
            f"MATCH (n) WHERE toLower(coalesce(n.name, '')) CONTAINS toLower('{kw}') "
            "RETURN labels(n) AS node_type, n.name AS name, n.file_path AS file_path, n.signature AS signature, n.code AS code"
        )
        return cypher


    def _run(self, user_query: str, file_path: str = '', **kwargs) -> str:
        self.chat_history = []

        # 1. 让LLM根据所有function schema自动选择function并给出参数
        callinfo = self.function_call_llm(user_query)
        if not callinfo or 'name' not in callinfo:
            # fallback: 走原有LLM流程
            primary_user_prompt = self.primary_user_prompt_template.template
            user_query_issue = f'<questions>\n{user_query}\n<\\questions>\n'
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
                answer_question, _ = extract_text_between_markers(
                    response_text, '[start_of_answer]', '[end_of_answer]')
                self.update_agent_message(
                    response_to_msg(extracted_analysis, extracted_code_search,
                                    answer_question))
                if not extracted_code_search and not answer_question:
                    msg = (
                        'The text between the markers [start_of_code_search] and [end_of_code_search], '
                        'as well as the text between the markers [start_of_answer] and [end_of_answer], is empty.'
                    )
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
                            'Please try writing simpler and clearer text queries, and ensure that '
                            'the corresponding parameters are correct.')
                        messages.append({'role': 'user', 'content': msg})
                    else:
                        messages.append({'role': 'user', 'content': user_response})
                        self.update_user_message(user_response)
                elif answer_question:
                    break
                if iter < self.max_iterations - 1:
                    msg = (
                        'Summarize your analysis first, and tell whether the current context is sufficient, '
                        'write your summarization here: \n'
                        '#### Concise Summarization:\n...\n'
                        "\nThen if it's sufficient, please continue answering in the following format:"
                        f'{CODE_SEARCH_FORMAT}'
                        "\nif it's not sufficient, please continue answering in the following format:"
                        f'{ANSWER_FORMAT}'
                        '\n\nNOTE:'
                        "\n- If you have already answered the user's question, do not write any search text queries."
                    )
                    messages.append({'role': 'user', 'content': msg})
            generate_queries = self.generate_queries_template.substitute(
                message='You are ready to do answer question.',
                user_query=user_query)
            messages.append({'role': 'user', 'content': generate_queries})
            answer = self.generate(messages)
            answer = markdown_answer(answer)
            self.update_agent_message(answer)
            return answer

        # 2. 分发到本地function，生成Cypher
        cypher_query = self.dispatch_function_call(callinfo)
        if cypher_query:
            user_response = self.cypher_agent.run(
                cypher_query, retries=self.max_iterations_cypher)
            self.update_user_message(user_response)
            # introduce_entity类型，自动分析总结
            if callinfo['name'] == 'introduce_entity':
                # 当需要介绍某个实体时，同时将与该实体相关的引用/调用节点也加入上下文，
                # 让 LLM 基于主节点与引用节点共同给出更完整的介绍。
                summary_prompt = (
                    "请根据以下 Cypher 查询结果，结合节点类型、名称、路径、签名、代码等信息，"
                    "对这些节点的功能进行总结分析，并用简明中文回答：\n"
                )

                # 主查询结果（直接匹配到的节点）
                summary_prompt += "\n【匹配到的节点】\n"
                if isinstance(user_response, list):
                    for node in user_response:
                        summary_prompt += (
                            f"类型: {node.get('node_type', '')}\n"
                            f"名称: {node.get('name', '')}\n"
                            f"路径: {node.get('file_path', '')}\n"
                            f"签名: {node.get('signature', '')}\n"
                            f"代码: {node.get('code', '')}\n\n"
                        )
                else:
                    summary_prompt += str(user_response) + "\n"

                # 同时查找引用/调用节点并加入上下文
                kw = None
                if isinstance(callinfo, dict):
                    kw = callinfo.get('arguments', {}).get('keyword')
                ref_nodes = None
                refs_cypher = None
                if kw:
                    try:
                        refs_cypher = self.find_references(kw)
                        # 运行引用查询并记录结果，便于确认引用查找已执行
                        ref_nodes = self.cypher_agent.run(refs_cypher, retries=self.max_iterations_cypher)
                        # 在 agent 消息中记录已执行的 Cypher，便于审计与调试
                        try:
                            self.update_agent_message(f"【引用查询已执行】 Cypher: {refs_cypher}")
                        except Exception:
                            pass
                    except Exception:
                        ref_nodes = None

                # 给出明显的标识，确认引用查找已执行，并展示数量/示例
                summary_prompt += "\n【与该实体相关的引用/调用节点（reference lookup 已执行）】\n"
                if refs_cypher:
                    summary_prompt += f"已执行引用查询 Cypher: {refs_cypher}\n"
                if isinstance(ref_nodes, list):
                    summary_prompt += f"检索到引用数量: {len(ref_nodes)}\n\n"
                    # 仅展示前 10 条以避免过长
                    for idx, node in enumerate(ref_nodes[:10], start=1):
                        summary_prompt += (
                            f"[{idx}] 来源类型: {node.get('from_labels', '')} | 来源名称: {node.get('from_name', '')} | 关系: {node.get('rel', '')} | 目标名称: {node.get('to_name', '')} | 目标路径: {node.get('to_file', '')}\n"
                        )
                    if len(ref_nodes) > 10:
                        summary_prompt += f"...（共 {len(ref_nodes)} 条，已显示前 10 条）\n"
                elif ref_nodes:
                    # 若返回非列表但存在结果，直接展示其文本化形式并标记
                    summary_prompt += "检索到非列表类型的引用结果（请查看原始返回以确认格式）：\n"
                    summary_prompt += str(ref_nodes) + "\n"
                else:
                    summary_prompt += "未检索到显著的引用/调用节点。\n"

                analysis = self.llm_call([{"role": "user", "content": summary_prompt}])
                return analysis
            # find_nodes_in_file 查询，先输出节点详细信息，再用 LLM 分析
            elif callinfo['name'] == 'find_nodes_in_file':
                node_info = "\n【节点详细信息】\n"
                summary_prompt = "请对以下节点的功能进行总结分析，并用简明中文回答：\n"
                if isinstance(user_response, list):
                    for node in user_response:
                        node_info += (
                            f"类型: {node.get('node_type', '')}\n"
                            f"名称: {node.get('name', '')}\n"
                            f"路径: {node.get('file_path', '')}\n"
                            f"签名: {node.get('signature', '')}\n"
                            f"代码: {node.get('code', '')}\n\n"
                        )
                        summary_prompt += (
                            f"类型: {node.get('node_type', '')}\n"
                            f"名称: {node.get('name', '')}\n"
                            f"路径: {node.get('file_path', '')}\n"
                            f"签名: {node.get('signature', '')}\n"
                            f"代码: {node.get('code', '')}\n\n"
                        )
                else:
                    node_info += str(user_response)
                    summary_prompt += str(user_response)
                analysis = self.llm_call([{"role": "user", "content": summary_prompt}])
                return f"{node_info}\n【自动分析总结】\n{analysis}"
            # 极简：find_call_hierarchy 只输出上游调用者和下游被调用者的名称（每行一个名称）
            elif callinfo['name'] == 'find_call_hierarchy':
                hierarchy_info = "\n【调用层级 - 名称列表】\n"

                callers = []
                callees = []
                if isinstance(user_response, list):
                    for row in user_response:
                        if isinstance(row, dict):
                            callers += row.get('callers') or []
                            callees += row.get('callees') or []
                elif isinstance(user_response, dict):
                    callers = user_response.get('callers') or []
                    callees = user_response.get('callees') or []
                else:
                    return str(user_response)

                # 提取名称并去重保序
                def _extract_name(e):
                    if isinstance(e, dict):
                        return e.get('from_name') or e.get('to_name') or e.get('name') or ''
                    return str(e)

                def _unique_names(seq):
                    seen = set()
                    out = []
                    for e in seq:
                        name = _extract_name(e).strip()
                        if not name:
                            continue
                        if name not in seen:
                            seen.add(name)
                            out.append(name)
                    return out

                callers = _unique_names(callers if isinstance(callers, list) else [callers])
                callees = _unique_names(callees if isinstance(callees, list) else [callees])

                hierarchy_info += "上游调用者 (callers):\n"
                if callers:
                    for name in callers[:200]:
                        hierarchy_info += f"- {name}\n"
                else:
                    hierarchy_info += "- 未发现上游调用者\n"

                hierarchy_info += "\n下游被调用者 (callees):\n"
                if callees:
                    for name in callees[:200]:
                        hierarchy_info += f"- {name}\n"
                else:
                    hierarchy_info += "- 未发现下游被调用者\n"

                return hierarchy_info
            else:
                # 其它find类型，只输出节点详细信息
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
                return node_info
        return ""

    def generate(self, messages):
        messages = deepcopy(messages)
        messages = replace_system_prompt(messages, SYSTEM_PROMPT)
        response_text = self.llm_call(messages)
        return response_text