from typing import Optional, Dict, Any
import os
import json

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

app = FastAPI()


class RunRequest(BaseModel):
    question: str
    language: Optional[str] = 'c'
    task_id: Optional[str] = 'local_test'
    llm_config: Optional[Dict[str, Any]] = None 
    graph_config: Optional[Dict[str, str]] = None
    prompt_path: Optional[str] = None
    schema_path: Optional[str] = None
    max_iterations: Optional[int] = 3


@app.post('/code_chat/run')
def run_code_chat(req: RunRequest):
    # Use incoming request fields as authoritative. Keep minimal defaults for local prompt/schema paths.
    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
    default_prompt = os.path.join(repo_root, 'apps', 'codexgraph_agent', 'prompt')
    default_schema = os.path.join(repo_root, 'apps', 'codexgraph_agent', 'prompt', 'graph_database')

    prompt_path = req.prompt_path or default_prompt
    schema_path = req.schema_path or default_schema

    # prepare graph db: require graph_config in the request
    graph_db = None
    gcfg = req.graph_config
    if not gcfg:
        raise HTTPException(status_code=400, detail='graph_config is required and must contain uri,user,password (and optional database_name).')
    try:
        from modelscope_agent.environment.graph_database.graph_database import GraphDatabaseHandler

        graph_db = GraphDatabaseHandler(
            gcfg.get('uri'), gcfg.get('user'), gcfg.get('password'),
            database_name=gcfg.get('database_name', 'neo4j'),
            task_id=req.task_id,
        )
    except Exception as e:
        import traceback
        tb = traceback.format_exc()
        raise HTTPException(status_code=500, detail=f'Failed to create GraphDatabaseHandler: {repr(e)}\n{tb}')

    # prepare llm: require llm_config in the request
    llm = req.llm_config
    if not llm:
        raise HTTPException(status_code=400, detail='llm_config is required and must describe the LLM (model, model_server, api_key).')

    # instantiate agent (Agent.__init__ will construct the real LLM when llm is a dict)
    try:
        from modelscope_agent.agents.codexgraph_agent.task.code_chat import CodexGraphAgentChat

        agent = CodexGraphAgentChat(
            llm=llm,
            prompt_path=prompt_path,
            schema_path=schema_path,
            task_id=req.task_id,
            graph_db=graph_db,
            language=req.language,
            max_iterations=req.max_iterations,
            message_callback=None,
        )
    except Exception as e:
        import traceback
        tb = traceback.format_exc()
        # include repr and traceback to help debug
        raise HTTPException(status_code=500, detail=f'Failed to construct agent: {repr(e)}\n{tb}')

    # run and return result
    try:
        result = agent.run(req.question)
    except Exception as e:
        import traceback
        tb = traceback.format_exc()
        raise HTTPException(status_code=500, detail=f'Agent run failed: {repr(e)}\n{tb}')

    return {'result': result}


if __name__ == '__main__':
    import uvicorn
    uvicorn.run(app=app, host='127.0.0.1', port=5200)
