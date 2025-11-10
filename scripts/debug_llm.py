import json, traceback, sys, os

# ensure repo root is on sys.path so we can import modelscope_agent
repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if repo_root not in sys.path:
    sys.path.insert(0, repo_root)

with open('scripts/request.json', 'r', encoding='utf-8') as f:
    req = json.load(f)
llm_cfg = req.get('llm_config')
print('LLM config:', llm_cfg)

try:
    from modelscope_agent.llm import get_chat_model
    # get_chat_model expects model, model_server as first two args when called
    llm = get_chat_model(**llm_cfg)
    print('LLM instance created:', type(llm), getattr(llm, 'model', None), getattr(llm, 'model_server', None))
    try:
        print('Sending a small test chat...')
        resp = llm.chat(messages=[{"role":"user","content":"Hello"}], max_tokens=4, stream=False)
        print('Chat response:', resp)
    except Exception as e:
        print('Error during chat call:', repr(e))
        traceback.print_exc()
except Exception as e:
    print('Failed to create LLM:', repr(e))
    traceback.print_exc()
