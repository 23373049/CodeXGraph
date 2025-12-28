from copy import deepcopy
import inspect

from modelscope_agent.agents.codexgraph_agent.cypher_agent import \
    CODE_SEARCH_FORMAT
from modelscope_agent.agents.codexgraph_agent.task.code_general import \
    CodexGraphAgentGeneral
from modelscope_agent.agents.codexgraph_agent.task.function_shared import \
    FunctionPlanningMixin
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

class CodexGraphAgentChat(FunctionPlanningMixin, CodexGraphAgentGeneral):

    def set_action_type_and_message(self):
        pass

    @staticmethod
    def _shorten_text(text, limit=160):
        """Condense multi-line LLM输出，保留主要信息。"""
        if text is None:
            return ''
        brief = str(text).strip().replace('\n', ' ')
        while '  ' in brief:
            brief = brief.replace('  ', ' ')
        if len(brief) > limit:
            brief = brief[:limit].rstrip() + '…'
        return brief

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
                "如果用户的提问为中文，那么提取的关键字keyword也必须为用户提到的中文关键字，不要自己解读为相近的其他词语或英文。\n"
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

    def function_planner_llm(self, user_query: str, initial_callinfo: dict = None):
        """
        让 LLM 先设计一个解决问题的步骤化计划（有序的 function 调用序列）。
        返回一个 list，每项为 {"name": <func_name>, "arguments": {"keyword": ...}}
        如果 LLM 无法返回合法 JSON，则返回 None 并由主流程回退到原有逻辑。
        """
        import json
        funcs = [func['name'] for func in self.FUNCTIONS]
        sys_msg = (
            "你是一个规划器。给出解决用户需求的分步计划，计划由若干步骤组成，"
            "每步为一个步骤对象(step)，可以是纯分析（不调用任何工具）或包含一个或多个工具调用。"
            "只有在确实需要从 Neo4j 中检索信息或调用本地工具时，才把相应的工具加入 calls。可用工具: %s。"
            "只返回一个 JSON 对象或数组，顶层为数组 (plan)。允许的步骤形式：\n"
            "1) 简单形式：{\"name\": 工具名, \"arguments\": {...}, \"rationale\": \"说明\"}（相当于单个 call 的步骤）；\n"
            "2) 多调用形式：{\"step_name\": \"描述性名称\", \"calls\": [{\"name\":工具名, \"arguments\": {...}, \"rationale\": \"说明\"}, ...], \"rationale\": \"本步说明\"}\n"
            "3) 纯分析形式：{\"step_name\": \"描述性名称\", \"analysis\": \"需要完成的思考/总结内容\", \"rationale\": \"可选说明\"}\n"
            "无论哪种形式，都可以额外提供 \"analysis\" 字段，用于说明本步需要侧重的分析要点；该字段可帮助后续步骤理解上下文。"
            "对于每个 call，arguments 只允许包含 keyword（或留空），rationale 为可选字符串。"
            "本地函数中需要的参数均为keyword，所以在arguments中只包含keyword即可，防止用户输入参数时带入其他参数导致错误。\n"
            "如果用户的提问为中文，那么提取的关键字keyword也必须为用户提到的中文关键字，不要自己解读为相近的其他词语或英文。\n"
        ) % funcs

        user_msg = (
            f"用户问题: {user_query}\n"
            "请设计尽可能精简且可执行的步骤来解决该问题，允许存在纯分析步骤；只有在确实需要时才安排工具调用。只输出 JSON，不要任何额外注释。"
        )

        messages = [
            {"role": "system", "content": sys_msg},
            {"role": "user", "content": user_msg}
        ]

        resp = self.llm_call(messages)
        # 解析 JSON。支持 str 或 dict 返回
        parsed = None
        try:
            if isinstance(resp, str):
                parsed = json.loads(resp)
            elif isinstance(resp, dict):
                parsed = resp
        except Exception:
            parsed = None

        if not parsed:
            return None

        # 支持两种返回格式：直接数组或 {"plan": [...]} 的对象
        if isinstance(parsed, dict) and 'plan' in parsed:
            plan = parsed['plan']
        elif isinstance(parsed, list):
            plan = parsed
        else:
            return None

        # 校验并规范化每个 step 到统一结构：{step_name, calls: [{name, arguments, rationale}], rationale}
        if not isinstance(plan, list):
            return None
        validated_steps = []
        valid_names = set(funcs)
        for idx, step in enumerate(plan, start=1):
            if not isinstance(step, dict):
                return None

            analysis_text = step.get('analysis') if isinstance(step.get('analysis'), str) else ''
            if analysis_text:
                analysis_text = analysis_text.strip()

            # 简单单-call 形式
            if 'name' in step and 'calls' not in step:
                name = step.get('name')
                if name not in valid_names:
                    if analysis_text:
                        step_name = step.get('step_name') or name or f'analysis_step_{idx}'
                        rationale = step.get('rationale', '') or ''
                        validated_steps.append({
                            'step_name': step_name,
                            'calls': [],
                            'rationale': rationale,
                            'analysis_instruction': analysis_text,
                            'analysis_only': True
                        })
                        continue
                    return None
                args = step.get('arguments', {}) or {}
                args = {'keyword': args.get('keyword', '')}
                rationale = step.get('rationale', '') or ''
                validated_steps.append({
                    'step_name': name,
                    'calls': [{'name': name, 'arguments': args, 'rationale': rationale}],
                    'rationale': rationale,
                    'analysis_instruction': analysis_text,
                    'analysis_only': False
                })
                continue

            # 多-call 形式
            calls = step.get('calls')
            if isinstance(calls, list):
                validated_calls = []
                for c in calls:
                    if not isinstance(c, dict) or 'name' not in c:
                        return None
                    cname = c.get('name')
                    if cname not in valid_names:
                        return None
                    carg = c.get('arguments', {}) or {}
                    carg = {'keyword': carg.get('keyword', '')}
                    cr = c.get('rationale', '') or ''
                    validated_calls.append({'name': cname, 'arguments': carg, 'rationale': cr})
                analysis_only = len(validated_calls) == 0
                if analysis_only and not analysis_text:
                    return None
                validated_steps.append({
                    'step_name': step.get('step_name') or (validated_calls[0]['name'] if validated_calls else step.get('name') or f'analysis_step_{idx}'),
                    'calls': validated_calls,
                    'rationale': step.get('rationale', '') or '',
                    'analysis_instruction': analysis_text,
                    'analysis_only': analysis_only
                })
                continue

            if analysis_text:
                step_name = step.get('step_name') or step.get('name') or f'analysis_step_{idx}'
                rationale = step.get('rationale', '') or ''
                validated_steps.append({
                    'step_name': step_name,
                    'calls': [],
                    'rationale': rationale,
                    'analysis_instruction': analysis_text,
                    'analysis_only': True
                })
                continue

            # 未识别的 step 形式
            return None

        # 如果提供了 initial_callinfo，优先使用其 keyword 作为规范化值，
        # 当 planner 返回的 keyword 为初始 keyword 的子串或更短的同义词时，替换为初始 keyword，保证跨步骤一致性。
        try:
            if initial_callinfo and isinstance(initial_callinfo, dict):
                init_kw = (initial_callinfo.get('arguments') or {}).get('keyword')
                if init_kw:
                    for step in validated_steps:
                        for c in (step.get('calls') or []):
                            try:
                                ckw = (c.get('arguments') or {}).get('keyword') or ''
                                # 若 planner 提供的 keyword 为空，或为 init_kw 的子串且更短，则用 init_kw 替换
                                if not ckw or (ckw and len(ckw) < len(init_kw) and init_kw.find(ckw) != -1):
                                    c['arguments']['keyword'] = init_kw
                            except Exception:
                                continue
        except Exception:
            pass

        return validated_steps


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

    def execute_call(self, callinfo: dict, step_input: str = None):
        """
        执行单个本地函数调用并返回其结果。支持：
        - 本地函数直接返回 Cypher 字符串 -> 自动调用 cypher_agent.run 并返回执行结果
        - 本地函数返回任意 Python 对象 -> 直接返回
        - 若本地函数签名接受额外的输入参数（如 'input' 或 'context'），会把 step_input 传入
        返回字典：{'raw': 原始返回值, 'executed': cypher 执行后的结果或原始返回}
        """
        import inspect
        name = callinfo.get('name')
        args = (callinfo.get('arguments') or {}).copy()
        func = getattr(self, name, None)
        result = {'raw': None, 'executed': None}
        if not func:
            result['raw'] = None
            result['executed'] = None
            return result

        # 如果函数接受 'input' 或 'context' 参数，则注入 step_input
        try:
            sig = inspect.signature(func)
            if 'input' in sig.parameters and 'input' not in args:
                args['input'] = step_input
            elif 'context' in sig.parameters and 'context' not in args:
                args['context'] = step_input
        except Exception:
            pass

        try:
            raw = func(**args)
            result['raw'] = raw
            # 如果 raw 看起来像 Cypher（粗略判断），则执行
            if isinstance(raw, str) and (raw.strip().lower().startswith('match') or ' return ' in raw.lower()):
                try:
                    exec_res = self.cypher_agent.run(raw, retries=self.max_iterations_cypher)
                    result['executed'] = exec_res
                except Exception:
                    result['executed'] = None
            else:
                result['executed'] = raw
        except Exception as e:
            result['raw'] = None
            result['executed'] = None
        return result

    def record_and_suggest_followups(self, user_query, analysis, overall_summary=None, collected=None, cumulative_memory=None):
        """
        记录本次 LLM 的回答到工作区持久化文件，并基于本次分析生成 3-6 个可供用户后续提问的建议。
        返回字典：{'memory_file': <path>, 'suggestions': <str>, 'entry': <dict>}
        """
        try:
            import os, json, time
        except Exception:
            return None

        workspace_root = getattr(self, 'workspace_root', None) or os.getcwd()
        mem_path = os.path.join(workspace_root, '.agent_memory.json')
        entry = {
            'timestamp': time.strftime('%Y-%m-%dT%H:%M:%S', time.localtime()),
            'user_query': str(user_query),
            'analysis': str(analysis),
            'overall_summary': str(overall_summary) if overall_summary is not None else None,
            'collected': None,
            'cumulative_memory': str(cumulative_memory) if cumulative_memory is not None else None
        }
        # 尝试简化 collected 结构以便序列化
        try:
            if collected is not None:
                # 保持关键信息：步骤名与每个调用的 keyword 与简短结果摘要
                simple = []
                for it in collected:
                    calls = []
                    for c in (it.get('calls') or []):
                        calls.append({
                            'name': c.get('call', {}).get('name'),
                            'keyword': c.get('call', {}).get('arguments', {}).get('keyword'),
                            'raw': (str(c.get('result', {}).get('raw'))[:1000] if c.get('result') else None),
                            'executed': (str(c.get('result', {}).get('executed'))[:1000] if c.get('result') else None),
                        })
                    simple.append({
                        'step_name': it.get('step_name'),
                        'rationale': it.get('rationale'),
                        'analysis_instruction': it.get('analysis_instruction'),
                        'analysis_only': bool(it.get('analysis_only')),
                        'calls': calls,
                        'step_analysis': (str(it.get('step_analysis'))[:2000] if it.get('step_analysis') else None)
                    })
                entry['collected'] = simple
        except Exception:
            entry['collected'] = None

        # 载入现有记忆并追加
        try:
            if os.path.exists(mem_path):
                try:
                    with open(mem_path, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                except Exception:
                    data = []
            else:
                data = []
            data.append(entry)
            with open(mem_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2, default=str)
        except Exception:
            # 写盘失败则忽略，不阻塞主流程
            pass

        # 基于 analysis / overall_summary 让 LLM 生成后续问题建议（3-6 条，每行一个）
        suggestions = ''
        try:
            prompt = (
                "请基于下面的用户问题、分析与（如有）最终总结，生成 3 到 6 个用户可以接着提问的、具体且可操作的后续问题。\n"
                "输出规范：只列出问题，每行一条，使用中文，不要额外解释。\n\n"
                f"用户问题：{user_query}\n\n分析：\n{analysis}\n\n最终汇总：\n{overall_summary if overall_summary else ''}\n"
            )
            # 与其他 llm_call 用法保持一致，传入 messages 列表
            suggestions = self.llm_call([{"role": "user", "content": prompt}])
            # 有时候 llm_call 返回的是复杂结构，转换为字符串
            if isinstance(suggestions, (list, dict)):
                try:
                    suggestions = json.dumps(suggestions, ensure_ascii=False)
                except Exception:
                    suggestions = str(suggestions)
        except Exception:
            suggestions = ''

        # 将 suggestions 附加到内存条目并重写一次文件
        try:
            entry['suggestions'] = str(suggestions)
            if os.path.exists(mem_path):
                with open(mem_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
            else:
                data = []
            # 最后一条通常为刚写入的，尝试替换它以包含 suggestions
            if data and isinstance(data, list):
                data[-1] = entry
                with open(mem_path, 'w', encoding='utf-8') as f:
                    json.dump(data, f, ensure_ascii=False, indent=2, default=str)
        except Exception:
            pass

        return {'memory_file': mem_path, 'suggestions': suggestions, 'entry': entry}

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

        # 2.a 先让 LLM 设计一个分步计划（可选）。如果规划器返回步骤序列，则按序执行每步并聚合结果，
        # 最后交给 LLM 生成最终答案；否则回退到原有的单步执行逻辑。
        plan = None
        try:
            plan = self.function_planner_llm(user_query, callinfo)
        except Exception:
            plan = None

        if plan:
            collected = []
            # 在执行前渲染 TODO 表，展示每步及 rationale，给用户可见的分析流程
            try:
                # 更友好的 TODO 展示：每项为序号 + 步骤名 + 简要说明 + 调用清单（name(keyword)）
                todo_table = "[Planned Steps]\n"
                for idx, s in enumerate(plan, start=1):
                    step_name = s.get('step_name') or f'step_{idx}'
                    rationale = s.get('rationale', '')
                    calls = s.get('calls') or []
                    analysis_instruction = s.get('analysis_instruction') or ''
                    if calls:
                        calls_brief = ", ".join([f"{c.get('name')}({c.get('arguments', {}).get('keyword','')})" for c in calls])
                    else:
                        calls_brief = "无工具调用"
                    todo_table += f"{idx}. {step_name} — {rationale}\n    调用: {calls_brief}\n"
                    if analysis_instruction:
                        todo_table += f"    分析指引: {analysis_instruction}\n"
                self.update_agent_message(todo_table)
            except Exception:
                pass
            # 支持多-call 的 step 执行：每步执行其 calls 列表，收集每个 call 的 raw/exec 结果，
            # 并在每步结束后调用 LLM 生成该步的思考输出（step_thought），作为下一步的输入。
            cumulative_memory = ''
            step_thoughts = []
            for step_idx, step in enumerate(plan, start=1):
                step_name = step.get('step_name') or f'step_{step_idx}'
                step_rationale = step.get('rationale', '')
                calls = step.get('calls') or []
                analysis_instruction = step.get('analysis_instruction', '') or ''
                analysis_only = bool(step.get('analysis_only'))
                step_calls_results = []
                for call in calls:
                    callinfo = {'name': call.get('name'), 'arguments': call.get('arguments', {})}
                    try:
                        exec_res = self.execute_call(callinfo, step_input=cumulative_memory)
                    except Exception:
                        exec_res = {'raw': None, 'executed': None}
                    step_calls_results.append({'call': callinfo, 'rationale': call.get('rationale',''), 'result': exec_res})
                    try:
                        # 记录每个 call 执行的 cypher 或 raw 返回，便于审计
                        self.update_agent_message(f"[planner executed] {callinfo.get('name')} -> {str(exec_res.get('raw') or exec_res.get('executed'))[:1000]}")
                    except Exception:
                        pass

                # 合成该步的分析（analysis），并把累积记忆（previous analyses + 本步分析）传给下一步
                try:
                    synth_prompt = (
                        f"你是一个代码分析助手。下面首先给出此前步骤的已知分析/记忆（如果有），\n"
                        f"{(cumulative_memory[:4000] + '...') if cumulative_memory else '(无)'}\n\n"
                        f"当前步骤名称: {step_name}\n"
                        f"步骤说明: {step_rationale if step_rationale else '(无)'}\n"
                    )
                    if analysis_instruction:
                        synth_prompt += f"步骤分析指引: {analysis_instruction}\n"
                    if step_calls_results:
                        synth_prompt += "本步骤执行的调用及返回：\n"
                        for idx_call, cres in enumerate(step_calls_results, start=1):
                            synth_prompt += f"调用 {idx_call}: 名称={cres['call']['name']} 说明={cres.get('rationale','')} 返回(raw)={str(cres['result'].get('raw'))[:800]} 返回(exec)={str(cres['result'].get('executed'))[:800]}\n"
                    else:
                        synth_prompt += "本步骤没有执行任何工具调用，主要根据已有记忆与指引继续推理。\n"
                    synth_prompt += (
                        "\n请基于已有记忆和本步骤的返回：\n"
                        "1) 给出本步骤的分析结论（1-3 句）；\n"
                        "2) 说明本步骤的返回如何改变或补充已有记忆（如果有）；\n"
                        "3) 输出不能包含 JSON，只返回纯文本的分析段落。"
                    )
                    step_analysis = self.llm_call([{"role": "user", "content": synth_prompt}])
                except Exception:
                    step_analysis = None

                # 将本步分析追加到累积记忆中，保留可读标签，限制总长度以防 prompt 过长
                try:
                    if step_analysis:
                        cumulative_memory = (cumulative_memory + "\n\n[Step %d Analysis]:\n" % step_idx + str(step_analysis)) if cumulative_memory else ("[Step %d Analysis]:\n" % step_idx + str(step_analysis))
                        # 保持累积记忆不超过一定大小（例如 15000 字符）
                        if len(cumulative_memory) > 15000:
                            cumulative_memory = cumulative_memory[-15000:]
                except Exception:
                    pass

                collected.append({
                    'step_index': step_idx,
                    'step_name': step_name,
                    'rationale': step_rationale,
                    'calls': step_calls_results,
                    'step_analysis': step_analysis,
                    'analysis_instruction': analysis_instruction,
                    'analysis_only': analysis_only
                })
                step_thoughts.append(step_analysis)

            # 聚合执行结果，交给 LLM 生成最终答案
            summary = "根据规划器设计并执行的步骤，以下是每步的调用与返回结果：\n"
            summary += f"用户问题: {user_query}\n\n"
            for item in collected:
                summary += f"步骤 {item.get('step_index')} 名称: {item.get('step_name')} 说明: {item.get('rationale')}\n"
                analysis_instruction = item.get('analysis_instruction') or ''
                calls = item.get('calls', [])
                if analysis_instruction:
                    summary += f"  分析指引: {analysis_instruction}\n"
                if calls:
                    for cidx, c in enumerate(calls, start=1):
                        summary += f"  调用 {cidx}: 名称={c['call'].get('name')} 参数={c['call'].get('arguments')} 说明={c.get('rationale','')}\n"
                        raw = c['result'].get('raw')
                        execd = c['result'].get('executed')
                        try:
                            if isinstance(execd, list):
                                summary += f"    执行结果数量: {len(execd)} 示例: {execd[:3]}\n"
                            else:
                                summary += f"    执行结果: {str(execd)[:1000]}\n"
                        except Exception:
                            summary += "    执行结果: (无法显示)\n"
                else:
                    summary += "  本步未调用任何工具，执行纯分析。\n"
                # 将本步由 LLM 产生的分析结果包含到 summary 中，便于最终答案观察每步思路
                summary += f"  本步思考（供下一步使用 & 展示）: {str(item.get('step_analysis'))[:2000]}\n\n"

            final_prompt = (
                "你是代码审查助手。请基于上面每步的执行结果，回答用户的原始问题，\n"
                "给出清晰、结构化的中文回复（先结论，再按部件列出职责与依据摘录）。\n"
            )
            final_prompt += summary
            analysis = self.llm_call([{"role": "user", "content": final_prompt}])

            # 生成一个简洁的最终汇总（Overall Summary），便于用户快速阅读要点
            overall_summary = None
            try:
                overall_prompt = (
                    "请基于下面的每步执行摘要和分析，输出一个简洁的最终总结（中文，3-6 句），\n"
                    "并列出 2-4 个最关键的证据项（按步骤编号引用）。\n\n"
                )
                overall_prompt += summary
                # 把 LLM 的完整回答也附上，帮助生成更一致的摘要
                overall_prompt += "\n\n当前 LLM 的详细回答为：\n" + (str(analysis) if analysis else '')
                overall_summary = self.llm_call([{"role": "user", "content": overall_prompt}])
            except Exception:
                overall_summary = None

            # 将规划步骤作为“思考流程”附加到最终回答中，便于用户查看LLM的分析过程
            try:
                plan_section = "\n【思考流程（Planned Steps）】\n\n"
                for item in collected:
                    idx = item.get('step_index')
                    name = item.get('step_name')
                    rationale = item.get('rationale') or ''
                    analysis_instruction = item.get('analysis_instruction') or ''
                    calls = item.get('calls', [])
                    step_analysis = item.get('step_analysis') or ''

                    main_goal = rationale or analysis_instruction or name or ''
                    main_goal = self._shorten_text(main_goal, 140)
                    plan_section += f"Step {idx}: {name}\n"
                    if main_goal:
                        plan_section += f"  主要动作: {main_goal}\n"

                    if calls:
                        call_desc = []
                        for c in calls:
                            cname = c['call'].get('name')
                            ckw = c['call'].get('arguments', {}).get('keyword', '')
                            if ckw:
                                call_desc.append(f"{cname}({ckw})")
                            else:
                                call_desc.append(cname)
                        plan_section += f"  调用函数: {', '.join(call_desc)}\n"
                    else:
                        operation = analysis_instruction or step_analysis or '无额外说明'
                        plan_section += f"  调用函数: 无\n  操作记录: {self._shorten_text(operation, 140)}\n"

                    if calls and step_analysis:
                        plan_section += f"  操作记录: {self._shorten_text(step_analysis, 140)}\n"

                    plan_section += "\n"
            except Exception:
                plan_section = "\n【思考流程（Planned Steps）】\n(无法生成规划步骤展示)\n"

            # 组合最终返回：详细回答 -> 最终汇总 -> 思考流程
            result_parts = []
            if analysis:
                result_parts.append(str(analysis))
            if overall_summary:
                result_parts.append("\n【最终汇总（Overall Summary）】\n" + str(overall_summary))
            result_parts.append(plan_section)
            try:
                mem = self.record_and_suggest_followups(user_query, analysis, overall_summary=overall_summary, collected=collected, cumulative_memory=cumulative_memory)
                if mem and mem.get('suggestions'):
                    result_parts.append("\n【后续可提问题建议】\n" + str(mem.get('suggestions')))
            except Exception:
                pass
            return "\n\n".join(result_parts)

        # 如果没有规划器返回或解析失败，则使用原有单步执行流程
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
                try:
                    mem = self.record_and_suggest_followups(user_query, analysis, overall_summary=None, collected=None, cumulative_memory=None)
                    suggestions = mem.get('suggestions','') if mem else ''
                except Exception:
                    suggestions = ''
                return f"{analysis}\n\n【后续可提问题建议】\n{suggestions}"
            elif callinfo['name'] == 'explain_feature_implementation':
                # 收敛检索到的实现片段，优先利用 description，辅以 code 片段，生成聚合说明
                feature = callinfo.get('arguments', {}).get('keyword', '')
                details = "\n【候选实现片段】\n"
                summary_prompt = (
                    "你是代码审查助手。请基于下列节点的 description 与 code 内容，\n"
                    "从“功能实现角度”回答：该功能主要由哪些模块/类/函数共同实现，各自负责什么，\n"
                    "并给出一个简洁、结构化的中文说明（先给结论，再给依据）。\n"
                )
                if feature:
                    summary_prompt += f"\n目标功能关键词：{feature}\n"
                if isinstance(user_response, list):
                    for node in user_response[:50]:  # 控制体量
                        details += (
                            f"类型: {node.get('node_type','')}\n"
                            f"名称: {node.get('name','')}\n"
                            f"路径: {node.get('file_path','')}\n"
                            f"签名: {node.get('signature','')}\n"
                            f"说明: {node.get('description','')[:500]}\n"
                            f"代码: {node.get('code','')[:500]}\n\n"
                        )
                else:
                    details += str(user_response)

                summary_prompt += details
                summary_prompt += (
                    "\n请输出：\n"
                    "1) 结论（一句话）：本功能的实现集中在哪些关键部件；\n"
                    "2) 关键实现清单：每个部件一句话职责（尽量引用节点名称与路径）；\n"
                    "3) 依据摘录：挑选若干最能支撑判断的 description/代码片段（可精简）。\n"
                )
                analysis = self.llm_call([{"role": "user", "content": summary_prompt}])
                try:
                    mem = self.record_and_suggest_followups(user_query, analysis, overall_summary=None, collected=None, cumulative_memory=None)
                    suggestions = mem.get('suggestions','') if mem else ''
                except Exception:
                    suggestions = ''
                return f"{analysis}\n\n【后续可提问题建议】\n{suggestions}"
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
                try:
                    mem = self.record_and_suggest_followups(user_query, analysis, overall_summary=None, collected=None, cumulative_memory=None)
                    suggestions = mem.get('suggestions','') if mem else ''
                except Exception:
                    suggestions = ''
                return f"{node_info}\n【自动分析总结】\n{analysis}\n\n【后续可提问题建议】\n{suggestions}"
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

                try:
                    mem = self.record_and_suggest_followups(user_query, hierarchy_info, overall_summary=None, collected=None, cumulative_memory=None)
                    suggestions = mem.get('suggestions','') if mem else ''
                except Exception:
                    suggestions = ''
                return hierarchy_info + "\n\n【后续可提问题建议】\n" + suggestions
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
                try:
                    mem = self.record_and_suggest_followups(user_query, node_info, overall_summary=None, collected=None, cumulative_memory=None)
                    suggestions = mem.get('suggestions','') if mem else ''
                except Exception:
                    suggestions = ''
                return node_info + "\n\n【后续可提问题建议】\n" + suggestions
        return ""

    def generate(self, messages):
        messages = deepcopy(messages)
        messages = replace_system_prompt(messages, SYSTEM_PROMPT)
        response_text = self.llm_call(messages)
        return response_text
