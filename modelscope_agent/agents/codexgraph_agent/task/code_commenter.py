import json
import logging
from typing import Any, Dict, List, Optional

from modelscope_agent.agents.codexgraph_agent.prompt import JSON_PROMPT
from modelscope_agent.agents.codexgraph_agent.task.code_general import \
    CodexGraphAgentGeneral
from modelscope_agent.agents.codexgraph_agent.utils.code_utils import \
    extract_and_parse_json
from modelscope_agent.agents.codexgraph_agent.utils.prompt_utils import \
    response_to_msg
from modelscope_agent.environment.graph_database import GraphDatabaseHandler

logger = logging.getLogger(__name__)


class CodexGraphAgentCommenter(CodexGraphAgentGeneral):

    FUNCTIONS = [
        {
            "name": "find_nodes_in_file",
            "description": (
                "列出某个源文件/头文件中包含的所有节点（函数、类/结构体等）。"
                "适用于如“展示 xxx.c 的所有内容”“show all nodes in foo.h”。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "keyword": {
                        "type": "string",
                        "description": "文件名或路径片段，例如 code_chat.py 或 drivers/uart/uart.c"
                    }
                },
                "required": ["keyword"]
            }
        },
        {
            "name": "find_class_by_keyword",
            "description": (
                "搜索类/结构体名称里包含关键词的定义，用于了解数据结构含义。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "keyword": {
                        "type": "string",
                        "description": "类或结构体名关键词，例如 Agent、Context"
                    }
                },
                "required": ["keyword"]
            }
        },
        {
            "name": "find_function_by_keyword",
            "description": (
                "搜索函数名称里包含关键词的定义，适合定位相关逻辑以便填写注释。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "keyword": {
                        "type": "string",
                        "description": "函数名关键词，例如 run、handle_request"
                    }
                },
                "required": ["keyword"]
            }
        },
        {
            "name": "introduce_entity",
            "description": (
                "对任意实体（模块、类、函数等）做简要介绍，帮助理解上下文。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "keyword": {
                        "type": "string",
                        "description": "实体名关键词，例如 code_chat、GraphAgent"
                    }
                },
                "required": ["keyword"]
            }
        },
        {
            "name": "find_references",
            "description": (
                "列出某实体在图中的引用/调用方，帮助描述函数用途或副作用。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "keyword": {
                        "type": "string",
                        "description": "目标实体关键词，例如 code_chat"
                    }
                },
                "required": ["keyword"]
            }
        },
        {
            "name": "find_call_hierarchy",
            "description": (
                "分析函数的调用链（上游调用者/下游被调者），便于在注释中说明依赖。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "keyword": {
                        "type": "string",
                        "description": "函数或方法名关键词，例如 process_request"
                    }
                },
                "required": ["keyword"]
            }
        },
    ]

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

    def set_action_type_and_message(self):
        self.action_type = 'ADD_COMMENTS'
        self.generate_message = 'You are ready to add code comments.'

    # ---------------------- helper methods ---------------------- #
    def _label_map(self):
        """Return label mapping per language (STRUCT/FILE for C)."""
        lang = (getattr(self, 'language', '') or '').lower()
        if lang.startswith('c'):
            return {
                'class_label': 'STRUCT',
                'module_label': 'FILE',
                'method_label': 'FUNCTION',
                'field_label': 'STRUCT_MEMBER',
                'function_label': 'FUNCTION'
            }
        return {
            'class_label': 'CLASS',
            'module_label': 'MODULE',
            'method_label': 'FUNCTION',
            'field_label': 'FIELD',
            'function_label': 'FUNCTION'
        }

    def function_call_llm(self, user_query: str) -> Optional[Any]:
        """Let the LLM choose one of the FUNCTIONS as a tool call."""
        tools = [func['name'] for func in self.FUNCTIONS]
        system_content = (
            "你是注释助手，在为代码补充注释前，可调用下列工具获取上下文。"
            "严格从提供的工具名称中选择一个，返回 JSON："
            '{"name":"<tool_name>","arguments":{"keyword":"<value>"}}\n'
            "不要输出解释或多余文本。"
            f"可用工具: {', '.join(tools)}。"
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
        raw = response if not isinstance(response, dict) else str(response)
        try:
            self.update_agent_message(
                f"[Commenter tool selection] raw_response={raw}")
        except Exception:
            logger.debug("[Commenter tool selection] %s", raw)
        return response

    def dispatch_function_call(self, callinfo: Dict[str, Any]) -> str:
        """Call local helper to build Cypher query."""
        name = callinfo.get('name')
        arguments = callinfo.get('arguments', {})
        try:
            self.update_agent_message(
                f"[Commenter dispatch] {name} args={arguments}")
        except Exception:
            logger.debug("[Commenter dispatch] %s %s", name, arguments)

        func = getattr(self, name, None)
        if func:
            return func(**arguments)
        return ''

    def find_nodes_in_file(self, keyword):
        return ("MATCH (n) "
                f"WHERE toLower(coalesce(n.file_path,'')) CONTAINS toLower('{keyword}') "
                "RETURN labels(n) AS node_type, n.name, n.file_path, n.signature, n.code")

    def find_class_by_keyword(self, keyword):
        labels = self._label_map()
        class_label = labels.get('class_label', 'CLASS')
        return (f"MATCH (c:{class_label}) "
                f"WHERE toLower(c.name) CONTAINS toLower('{keyword}') "
                "RETURN c.name, c.file_path, c.signature, c.code")

    def find_function_by_keyword(self, keyword):
        labels = self._label_map()
        method_label = labels.get('method_label', 'FUNCTION')
        return (f"MATCH (f:{method_label}) "
                f"WHERE toLower(f.name) CONTAINS toLower('{keyword}') "
                "RETURN f.name, f.file_path, f.signature, f.code")

    def introduce_entity(self, keyword):
        return ("MATCH (n) "
                f"WHERE toLower(n.name) CONTAINS toLower('{keyword}') "
                "RETURN labels(n) AS node_type, n.name, n.file_path, n.code")

    def find_references(self, keyword):
        return (
            "MATCH (t) WHERE toLower(t.name) CONTAINS "
            f"toLower('{keyword}') "
            "MATCH (a)-[r]->(t) "
            "RETURN labels(a) AS from_labels, a.name AS from_name, "
            "type(r) AS rel, labels(t) AS to_labels, t.name AS to_name, "
            "t.file_path AS to_file"
        )

    def find_call_hierarchy(self, keyword):
        return (
            "MATCH (t) WHERE toLower(t.name) CONTAINS "
            f"toLower('{keyword}') "
            "OPTIONAL MATCH (caller)-[r1:CALLS|USES*1..2]->(t) "
            "OPTIONAL MATCH (t)-[r2:CALLS|USES*1..2]->(callee) "
            "RETURN DISTINCT labels(t) AS target_labels, t.name AS target_name, "
            "t.file_path AS target_file, "
            "collect(DISTINCT {from_labels: labels(caller), "
            "from_name: caller.name, rel: type(r1)}) AS callers, "
            "collect(DISTINCT {to_labels: labels(callee), "
            "to_name: callee.name, rel: type(r2)}) AS callees"
        )

    def _gather_context_messages(self, user_query: str) -> List[str]:
        """Optionally fetch context via tool calls; return extra messages."""
        context_messages: List[str] = []

        try:
            callinfo = self.function_call_llm(user_query)
        except Exception as exc:
            logger.debug("function_call_llm failed: %s", exc)
            return context_messages

        call_list: List[Dict[str, Any]] = []
        if isinstance(callinfo, list):
            call_list = [c for c in callinfo if isinstance(c, dict)]
        elif isinstance(callinfo, dict) and callinfo.get('name'):
            call_list = [callinfo]

        if not call_list:
            return context_messages

        aggregated_results = []
        for idx, single_call in enumerate(call_list, start=1):
            cypher_query = self.dispatch_function_call(single_call)
            if not cypher_query:
                aggregated_results.append({
                    'call': single_call,
                    'result': None,
                    'error': 'no cypher generated'
                })
                continue

            try:
                user_response = self.cypher_agent.run(
                    cypher_query, retries=self.max_iterations_cypher)
            except Exception as exc:
                logger.exception("cypher_agent.run failed")
                aggregated_results.append({
                    'call': single_call,
                    'result': None,
                    'error': str(exc)
                })
                continue

            try:
                preview = str(user_response)
                self.update_agent_message(
                    f"[Commenter tool result #{idx}] {preview[:2000]}")
            except Exception:
                logger.debug("tool result #%s: %s", idx, user_response)

            aggregated_results.append({
                'call': single_call,
                'result': user_response,
                'error': None
            })

        if not aggregated_results:
            return context_messages

        node_info = "### Retrieved context from graph database\n"
        for entry in aggregated_results:
            call = entry['call']
            node_info += f"- tool: {call.get('name')} args={call.get('arguments')}\n"
            if entry['error']:
                node_info += f"  error: {entry['error']}\n"
            else:
                snippet = str(entry['result'])
                node_info += f"  result preview: {snippet[:1000]}\n"

        context_messages.append(node_info)

        try:
            analysis = self.llm_call([{
                'role':
                'user',
                'content':
                f'请基于以下内容给出简要总结，帮助理解代码注释上下文：\n{node_info}'
            }])
        except Exception:
            analysis = ''

        if analysis:
            context_messages.append(f"【自动分析总结】\n{analysis}")

        return context_messages

    # ---------------------- main run loop ---------------------- #
    def _run(self, user_query: str, file_path: str = '', **kwargs) -> str:
        self.chat_history = []

        extra_messages = self._gather_context_messages(user_query)

        if file_path:
            file_path = f'# file path: {file_path}'

        primary_user_prompt = self.primary_user_prompt_template.substitute(
            file_path=file_path, user_query=user_query)

        messages = [
            {
                'role': 'system',
                'content': self.system_prompts
            },
            {
                'role': 'user',
                'content': primary_user_prompt
            },
        ]
        self.chat_history.append(('system', self.system_prompts))

        for msg in extra_messages:
            messages.append({'role': 'user', 'content': msg})
            self.update_user_message(msg)

        generate_msg = self.generate_message

        for iter in range(self.max_iterations):

            if iter == self.max_iterations - 1:
                generate_msg = 'You have exhausted all query opportunities.'

            response_text = self.llm_call(messages)
            messages.append({'role': 'assistant', 'content': response_text})
            parsed_response, error_msg = extract_and_parse_json(response_text)

            if error_msg:
                user_response = (
                    'Something wrong with the JSON format, please rewrite it '
                    'and follow the given format:\n'
                    f'{JSON_PROMPT}')
                messages.append({'role': 'user', 'content': user_response})
                continue

            thought, action, action_input = parsed_response.values()

            self.update_agent_message(
                response_to_msg(thought, action, action_input))

            if action == self.action_type:
                break

            elif action == 'TEXT_QUERIES':
                cypher_queries = self.cypher_queries_template.substitute(
                    text_queries=action_input)
                user_response = self.cypher_agent.run(
                    cypher_queries, retries=self.max_iterations_cypher)
            else:
                user_response = (f'Invalid action, the action should be '
                                 f'`{self.action_type}` or `TEXT_QUERIES`')

            messages.append({'role': 'user', 'content': user_response})
            self.update_user_message(user_response)

        generate_queries = self.generate_queries_template.substitute(
            message=generate_msg, file_path=file_path, user_query=user_query)

        messages.append({'role': 'user', 'content': generate_queries})
        answer = self.llm_call(messages)

        self.update_user_message(generate_queries)
        self.update_agent_message(answer)
        messages.append({'role': 'assistant', 'content': answer})

        return answer

