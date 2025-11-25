import os
from pathlib import Path

import streamlit as st
from apps.codexgraph_agent.pages.components.page import (PageBase,
                                                         get_llm_config)
from modelscope_agent.agents.codexgraph_agent import CodexGraphAgentDebugger


class CodeDebuggerPage(PageBase):

    def __init__(self):
        super().__init__(
            task_name='code_debugger',
            page_title='🛠️ Code Debugger',
            output_path='logs/CD_conversation',
            input_title='Bug Issue',
            default_input_text=(
                'Please copy and paste the code snippet and describe the bug '
                'or issue you are facing. '
                'Include any error messages if available.'))
        self.agent = self.get_agent()

    def get_agent(self):
        graph_db = self.get_graph_db(
            st.session_state.shared['setting']['project_id'])

        if not graph_db:
            return None

        llm_config = get_llm_config(
            st.session_state.shared['setting']['llm_model_name'])

        max_iterations = int(
            st.session_state.shared['setting']['max_iterations'])

        prompt_path = str(
            Path(st.session_state.shared['setting']['prompt_path']).joinpath(
                'code_debugger'))
        schema_path = str(
            Path(st.session_state.shared['setting']['prompt_path']).joinpath(
                'graph_database'))
        language = st.session_state.shared['setting'].get('language', 'python')

        try:
            # 打印调试信息
            print(f"[DEBUG] LLM Config: {llm_config}")
            print(f"[DEBUG] API Key present: {'api_key' in llm_config if llm_config else False}")
            if llm_config and 'api_key' in llm_config:
                masked_key = f"{llm_config['api_key'][:10]}...{llm_config['api_key'][-4:]}" if len(llm_config['api_key']) > 14 else "***"
                print(f"[DEBUG] API Key: {masked_key}")
            
            agent = CodexGraphAgentDebugger(
                llm=llm_config,
                prompt_path=prompt_path,
                schema_path=schema_path,
                task_id=st.session_state.shared['setting']['project_id'],
                language=language,
                graph_db=graph_db,
                max_iterations=max_iterations,
                message_callback=self.create_update_message())
            print(f"[DEBUG] Agent initialized successfully")
        except Exception as e:
            import traceback
            error_msg = f'Failed to initialize agent: {str(e)}'
            print(f'[ERROR] {error_msg}')
            print(f'[ERROR] Traceback: {traceback.format_exc()}')
            print(
                f'[ERROR] Prompt path: {prompt_path},  '
                f'Schema path: {schema_path}, LLM config: {llm_config}'
            )
            # 显示更友好的错误信息
            st.error(f'Agent initialization failed: {str(e)}\n\nPlease check:\n1. API key is set correctly\n2. API base URL is accessible\n3. Check console for detailed error messages')
            agent = None
        return agent


def show():
    page = CodeDebuggerPage()
    page.main()


if __name__ == '__main__':
    page = CodeDebuggerPage()
    page.main()
