import os
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from modelscope_agent.environment.graph_database import GraphDatabaseHandler
from modelscope_agent.environment.graph_database.ast_search import AstManager


def get_py_files(directory):
    py_files = []
    for root, dirs, files in os.walk(directory):
        for file in files:
            if file.endswith('.py'):
                py_files.append(os.path.join(root, file))
    return py_files


def run_single(path, root, task_id, shallow, env_path_dict=None):

    env_path = env_path_dict['env_path']
    script_path = os.path.join(env_path_dict['working_directory'],
                               'run_index_single.py')
    working_directory = env_path_dict['working_directory']
    url = env_path_dict['url']
    user = env_path_dict['user']
    password = env_path_dict['password']
    db_name = env_path_dict['db_name']

    if shallow:
        script_args = [
            '--file_path',
            path,
            '--root_path',
            root,
            '--task_id',
            task_id,
            '--url',
            url,
            '--user',
            user,
            '--password',
            password,
            '--db_name',
            db_name,
            '--env',
            env_path,
            '--shallow',
        ]
    else:
        script_args = [
            '--file_path', path, '--root_path', root, '--task_id', task_id
        ]
    return run_script_in_env(env_path, script_path, working_directory,
                             script_args)


def run_script_in_env(env_path,
                      script_path,
                      working_directory,
                      script_args=None):
    # python_executable = os.path.join(env_path, "bin", "python")
    if not os.path.exists(env_path):
        raise FileNotFoundError(
            'Python executable not found in the environment: {}'.format(
                env_path))

    command = [env_path, script_path]
    if script_args:
        command.extend(script_args)
    # print(' '.join(command))

    try:
        result = subprocess.run(
            command,
            cwd=working_directory,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        stdout = result.stdout.decode('utf-8')
        stderr = result.stderr.decode('utf-8')

        if result.returncode == 0:
            return 'Script executed successfully:\n{}'.format(stdout)
        else:
            return 'Script execution failed:\n{}'.format(stderr)
    except subprocess.CalledProcessError as e:
        return 'Error: {}'.format(e.stderr)


def build_graph_database(graph_db: GraphDatabaseHandler,
                         repo_path: str,
                         task_id: str,
                         is_clear: bool = True,
                         max_workers=None,
                         env_path_dict=None,
                         update_progress_bar=None,
                         language: str = 'Python'):
    """
    Build the graph database for given repository.

    Supports Python (existing flow) and C (integrates functions from replace/).
    """
    root_path = repo_path

    # Clear data for the task first
    if is_clear:
        try:
            graph_db.clear_task_data(task_id=task_id)
        except Exception:
            # fallback to clear_database if clear_task_data not available
            try:
                graph_db.clear_database()
            except Exception:
                pass

    start_time = time.time()

    # If language is C, use the C analyzer from replace/
    if language and language.lower() == 'c':
        # Import replace modules dynamically. Ensure repo root on path.
        import sys
        import json
        from pathlib import Path
        repo_root = Path(__file__).resolve().parents[3]
        if str(repo_root) not in sys.path:
            sys.path.insert(0, str(repo_root))
        # Also add the `replace` folder to sys.path so modules like
        # `ast_visitor_client.py`, `c_ast_traverser.py`, `mock_dependencies.py`
        # (which live under replace/) can be imported as top-level modules.
        replace_dir = repo_root.joinpath('replace')
        if str(replace_dir) not in sys.path:
            sys.path.insert(0, str(replace_dir))
            
        # Load Neo4j settings from setting.json
        setting_path = repo_root / 'apps' / 'codexgraph_agent' / 'setting.json'
        try:
            with open(setting_path, 'r', encoding='utf-8') as f:
                settings = json.load(f)
                neo4j_settings = settings['setting']['neo4j']
        except Exception as e:
            print(f"Failed to load Neo4j settings from setting.json: {e}")
            neo4j_settings = {
                'url': 'bolt://localhost:7687',
                'user': 'neo4j',
                'password': 'password',
                'database_name': 'neo4j'
            }

        # Local adapter to provide the API expected by replace's AstVisitorClient
        class ReplaceGraphDBAdapter:
            def __init__(self, graphdb_handler: GraphDatabaseHandler, task_id: str):
                self._g = graphdb_handler
                self._task_id = task_id

            def add_node(self, label=None, full_name=None, parms=None, **kwargs):
                # Match replace API: add_node(label, full_name, parms)
                return self._g.add_node(label, full_name, parms)

            def add_edge(self, start_label=None, start_name=None, relationship_type=None, end_label=None, end_name=None, params=None, **kwargs):
                return self._g.add_edge(start_label, start_name, relationship_type, end_label, end_name, params)

            def get_node(self, full_name=None, **kwargs):
                # Return a dict similar to replace.Neo4jGraphDatabase.get_node
                try:
                    q = "MATCH (n {full_name: $full_name}) RETURN n"
                    rows = self._g.execute_query(q, full_name=full_name)
                    if not rows:
                        return None
                    # rows are py2neo Node-like wrapped as records; try to extract
                    record = rows[0]
                    # record could be a py2neo Node or a mapping
                    n = list(record.values())[0]
                    if hasattr(n, 'items'):
                        node_props = dict(n)
                    else:
                        node_props = dict(n)
                    return {
                        'id': node_props.get('id'),
                        'label': node_props.get('type'),
                        'full_name': node_props.get('full_name', node_props.get('id')),
                        'parms': {k: v for k, v in node_props.items() if k not in ['id', 'type', 'full_name']}
                    }
                except Exception:
                    return None

            def update_edge(self, edge_id, new_end_name=None, new_end_label=None, **kwargs):
                # Try to rewire relationship by internal id
                try:
                    q = """
                    MATCH (s)-[r]->(t)
                    WHERE id(r) = $edge_id
                    WITH s, r
                    MATCH (newt {full_name: $new_end_name})
                    CREATE (s)-[newr:CALL]->(newt)
                    SET newr = properties(r)
                    DELETE r
                    RETURN true
                    """
                    self._g.execute_query(q, edge_id=edge_id, new_end_name=new_end_name)
                    return True
                except Exception:
                    return False

            def delete_node(self, full_name=None, **kwargs):
                try:
                    q = "MATCH (n {full_name: $full_name}) DETACH DELETE n"
                    self._g.execute_query(q, full_name=full_name)
                    return True
                except Exception:
                    return False

            @property
            def nodes(self):
                try:
                    q = "MATCH (n) RETURN n"
                    rows = self._g.execute_query(q)
                    nodes = {}
                    for rec in rows:
                        n = list(rec.values())[0]
                        props = dict(n)
                        full_name = props.get('full_name', props.get('id'))
                        nodes[full_name] = {
                            'id': props.get('id'),
                            'label': props.get('type'),
                            'full_name': full_name,
                            'parms': {k: v for k, v in props.items() if k not in ['id', 'type', 'full_name']}
                        }
                    return nodes
                except Exception:
                    return {}

            @property
            def edges(self):
                try:
                    q = "MATCH (s)-[r]->(t) RETURN s.id AS start_name, type(r) AS relationship_type, properties(r) AS props, t.id AS end_name, id(r) AS edge_id"
                    rows = self._g.execute_query(q)
                    edges = []
                    for rec in rows:
                        edges.append({
                            'id': rec.get('edge_id'),
                            'start_name': rec.get('start_name'),
                            'relationship_type': rec.get('relationship_type'),
                            'end_name': rec.get('end_name'),
                            'params': rec.get('props') or {}
                        })
                    return edges
                except Exception:
                    return []

        # import c analyzer pieces
        try:
            from ast_visitor_client import AstVisitorClient
            from c_ast_traverser import traverse_c_ast_and_record
        except Exception as e:
            return f"Failed to import C analyzer components: {e}"

        # collect source files
        def find_source_files(base_dir, extensions=['.c', '.cpp', '.h', '.hpp']):
            files = []
            for root, _, filenames in __import__('os').walk(base_dir):
                for fn in filenames:
                    if any(fn.endswith(ext) for ext in extensions):
                        files.append(__import__('os').path.join(root, fn))
            return files

        file_list = find_source_files(repo_path)
        total_files = len(file_list) or 1

        # progress start
        if update_progress_bar:
            update_progress_bar(0.0)

        # 从 replace/ 导入 Neo4jGraphDatabase 并使用 setting.json 中的配置
        try:
            from neo4j_graph_database import Neo4jGraphDatabase

            try:
                # 使用从 setting.json 加载的配置创建 Neo4j 连接
                replace_db = Neo4jGraphDatabase(
                    uri=neo4j_settings['url'],
                    user=neo4j_settings['user'],
                    password=neo4j_settings['password'],
                    database=neo4j_settings.get('database_name', 'neo4j'),
                    task_label=task_id,
                )
                # 清空数据库并创建索引
                replace_db.clear_database()
                replace_db.create_indexes()
                print(f"✓ Connected to Neo4j at {neo4j_settings['url']} using setting.json configuration")
                adapter = replace_db
            except Exception as conn_err:
                # 连接失败则使用原有适配器（基于 GraphDatabaseHandler）
                print(f"Failed to connect using Neo4jGraphDatabase: {conn_err}")
                print("Falling back to GraphDatabaseHandler adapter...")
                adapter = ReplaceGraphDBAdapter(graph_db, task_id)
        except ImportError as imp_err:
            # 无法导入 replace 的 neo4j 实现，回退到适配器
            print(f"Could not import Neo4jGraphDatabase: {imp_err}")
            print("Falling back to GraphDatabaseHandler adapter...")
            adapter = ReplaceGraphDBAdapter(graph_db, task_id)

        client = AstVisitorClient(adapter, task_root_path=repo_path)

        # traverse each file sequentially (C analysis can be complex; avoid heavy parallelism here)
        for i, file_path in enumerate(sorted(file_list)):
            try:
                traverse_c_ast_and_record(client, file_path)
            except Exception as e:
                msg = f"`{file_path}` generated an exception: `{e}`"
                print(msg)
                return msg
            finally:
                if update_progress_bar:
                    update_progress_bar((i + 1) / total_files)

        # post process
        try:
            client.post_process_references()
        except Exception as e:
            print(f"post_process_references error: {e}")

        end_time = time.time()
        elapsed_time = end_time - start_time
        print(f'✍️ C indexing ({int(elapsed_time)} s)')
        # 返回 None 表示成功
        return None

    # Default Python flow (existing behavior)
    file_list = get_py_files(repo_path)
    total_files = len(file_list) or 1

    if update_progress_bar:
        update_progress_bar(0.5 / total_files)

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_file = {
            executor.submit(run_single, file_path, root_path, task_id, True,
                            env_path_dict): file_path
            for file_path in file_list
        }
        for i, future in enumerate(as_completed(future_to_file)):
            file_path = future_to_file[future]
            try:
                future.result()
                print('Successfully processed {}'.format(file_path))
            except Exception as exc:
                msg = '`{}` generated an exception: `{}`'.format(
                    file_path, exc)
                print(msg)
                # 在捕获到异常后，停止提交新任务，并尝试取消所有未完成的任务
                executor.shutdown(wait=False, cancel_futures=True)
                return msg
            finally:
                # 每完成一个任务，更新进度条
                if update_progress_bar:
                    update_progress_bar((i + 1) / total_files)
                # print((i+1) / total_files)
    # ast, class inheritance
    ast_manage = AstManager(repo_path, task_id, graph_db)
    ast_manage.run()

    end_time = time.time()
    elapsed_time = end_time - start_time
    print(f'✍️ Shallow indexing ({int(elapsed_time)} s)')
    return None
