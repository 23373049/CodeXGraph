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

    def question_to_cypher(self, question: str) -> str:
        # 查找某个文件下的所有节点
        match = re.search(r'find nodes in file ([\w\.\-]+)', question, re.IGNORECASE)
        if match:
            filename = match.group(1).strip()
            return f"MATCH (n) WHERE n.file_path CONTAINS '{filename}' RETURN labels(n) AS node_type, n.name, n.file_path, n"
        # introduce the xxx: 在所有节点类型中查找 name 包含关键字的节点
        match = re.search(r'introduce the ([\w_\-]+)', question, re.IGNORECASE)
        if match:
            keyword = match.group(1).strip()
            return (
                "MATCH (n) WHERE n.name CONTAINS '{keyword}' "
                "RETURN labels(n) AS node_type, n.name, n.file_path, n"
            ).format(keyword=keyword)
        # 查找MODULE名称中包含关键词
        match = re.search(r'find module contains ([\w_\-]+)', question, re.IGNORECASE)
        if match:
            keyword = match.group(1).strip()
            return f"MATCH (m:MODULE) WHERE m.name CONTAINS '{keyword}' RETURN m.name, m.file_path"
        # 查找GLOBAL_VARIABLE名称中包含关键词
        match = re.search(r'find global_variable contains ([\w_\-]+)', question, re.IGNORECASE)
        if match:
            keyword = match.group(1).strip()
            return f"MATCH (g:GLOBAL_VARIABLE) WHERE g.name CONTAINS '{keyword}' RETURN g.name, g.file_path, g.code"
        # 查找CLASS名称中包含关键词
        match = re.search(r'find class contains ([\w_\-]+)', question, re.IGNORECASE)
        if match:
            keyword = match.group(1).strip()
            return f"MATCH (c:CLASS) WHERE c.name CONTAINS '{keyword}' RETURN c.name, c.file_path, c.signature, c.code"
        # 查找METHOD名称中包含关键词
        match = re.search(r'find method contains ([\w_\-]+)', question, re.IGNORECASE)
        if match:
            keyword = match.group(1).strip()
            return f"MATCH (m:METHOD) WHERE m.name CONTAINS '{keyword}' RETURN m.name, m.file_path, m.class, m.signature, m.code"
        # 查找FIELD名称中包含关键词
        match = re.search(r'find field contains ([\w_\-]+)', question, re.IGNORECASE)
        if match:
            keyword = match.group(1).strip()
            return f"MATCH (f:FIELD) WHERE f.name CONTAINS '{keyword}' RETURN f.name, f.file_path, f.class"
        # 查找FUNCTION名称中包含关键词
        match = re.search(r'find function contains ([\w_\-]+)', question, re.IGNORECASE)
        if match:
            keyword = match.group(1).strip()
            return f"MATCH (f:FUNCTION) WHERE f.name CONTAINS '{keyword}' RETURN f.name, f.file_path, f.signature, f.code"

        return ""

    def _run(self, user_query: str, file_path: str = '', **kwargs) -> str:
        self.chat_history = []

        # 优先尝试用规则方法生成 Cypher,如果生成了就直接执行,否则走原来的流程(使用LLM)
        cypher_query = self.question_to_cypher(user_query)
        if cypher_query:
            user_response = self.cypher_agent.run(
                cypher_query, retries=self.max_iterations_cypher)
            self.update_user_message(user_response)

            # 判断查询类型
            if re.search(r'introduce the ([\w_\-]+)', user_query, re.IGNORECASE):
                # 构造分析 prompt，仅输出 LLM 总结
                summary_prompt = "请根据以下 Cypher 查询结果，结合节点类型、名称、路径、签名、代码等信息，对这些节点的功能进行总结分析，并用简明中文回答：\n"
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
                    summary_prompt += str(user_response)
                analysis = self.llm_call([{"role": "user", "content": summary_prompt}])
                return analysis
            # find nodes in file 查询
            elif re.search(r'find nodes in file ([\w\.\-]+)', user_query, re.IGNORECASE):
                # find nodes in file 查询，先输出节点详细信息，再用 LLM 分析
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
            else:
                # find contains 查询，只输出节点详细信息
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

    def generate(self, messages):
        messages = deepcopy(messages)
        messages = replace_system_prompt(messages, SYSTEM_PROMPT)
        response_text = self.llm_call(messages)
        return response_text
