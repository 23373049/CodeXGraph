# 将 C 语言分析并写入 Neo4j 集成到 CodexGraph — 变更说明

## 概要

主要工作是：

- 在 `modelscope_agent` 的 graph-database 构建流程中，新增对 `language='C'` 的分支，从而调用 `replace/` 目录下的独立 C 分析实现（tree-sitter + 自定义 visitor），并将结果写入 Neo4j（或回退到主项目的 GraphDatabaseHandler 适配器）。
- 新增 `replace/` 目录下的一套独立实现：C AST 遍历器（`c_ast_traverser.py`）、客户端适配器（`ast_visitor_client.py`）、Neo4j 专用实现（`neo4j_graph_database.py`）以及模拟依赖（`mock_dependencies.py`）、辅助脚本与示例仓库。
- 在 `modelscope_agent` 中增加对 language 配置的传播（如 Page setting、Agent 初始化等），并把语言信息传递到 Agent / 构建流程中。

这些更改允许用户在设置中选择 `C`，并使用新的 C 分析器构建代码图（并写入 Neo4j），同时保持对原有 Python 流程的兼容性。

## 修改的主要文件（摘录）

- `modelscope_agent/environment/graph_database/build.py` — 在构建函数 `build_graph_database` 中新增 `language` 参数与 C 分支逻辑，负责：
  - 动态添加 repo 根与 `replace` 文件夹到 `sys.path`，加载 `replace` 实现；
  - 读取 `apps/codexgraph_agent/setting.json` 中的 Neo4j 配置作为 fallback；
  - 提供一个 `ReplaceGraphDBAdapter`，把主仓库的 `GraphDatabaseHandler` 适配成 `replace` 代码期待的 API；
  - 调用 `AstVisitorClient` + `traverse_c_ast_and_record` 对 C 源文件逐个分析并写入图数据库。

- `replace/ast_visitor_client.py` — C 分析的客户端（visitor）实现，负责把解析得到的符号/作用域/引用转换为图数据库操作（节点、边），并提供后处理（`post_process_references`）用于解析未确定引用。

- `replace/c_ast_traverser.py` — 使用 tree-sitter 解析 C/CPP 源文件、深度遍历 AST，并将函数、结构体、typedef、宏、调用、include 等事件记录到 `AstVisitorClient`。

- `replace/neo4j_graph_database.py` — 真实 Neo4j 客户端实现（兼容 MockGraphDB 风格），提供 `add_node`/`add_edge`/`update_edge`/`get_node` 等方法，供 `replace` 中的逻辑直接调用。


## 设计要点与实现细节

1) 在构建入口中支持 C

在 `build_graph_database(graph_db, repo_path, task_id, ..., language='Python')` 中新增 `language` 参数，并在检测到 `language.lower() == 'c'` 时走 C 分支：

- 把仓库根与 `replace` 目录加入 `sys.path`，以便导入 `replace` 下的模块（`ast_visitor_client`、`c_ast_traverser`、`neo4j_graph_database` 等）。
- 从 `apps/codexgraph_agent/setting.json` 读取 Neo4j 的连接配置，若不可用则使用默认配置。
- 提供 `ReplaceGraphDBAdapter`：一个轻量适配层，把主项目的 `GraphDatabaseHandler`（或任意实现）转换为 `replace` 子系统期望的 API（例如 `add_node(label, full_name, parms)`、`add_edge(...)`、`get_node(full_name)`、`update_edge`、`delete_node`、`nodes`/`edges` 属性等）。

2) C 分析器（replace/*）

- `c_ast_traverser.py` 使用 tree-sitter 的 C 语法，遍历 AST，识别关键节点：函数定义、函数声明、全局变量、struct/union/enum、typedef、宏、调用表达式、include 指令等。
- 对每个识别到的符号，调用 `AstVisitorClient.recordSymbol(...)` / `recordSymbolKind(...)` / `recordReference(...)` / `recordSymbolScopeLocation(...)` 等方法将信息写入图数据库。
- 在所有文件处理完后，调用 `AstVisitorClient.post_process_references()` 做后处理：把临时 UNKNOWN 占位符解析到真实定义（如果可以），并更新关系（例如把指向临时节点的 CALL/USAGE 边重定向到真实定义），最后清理孤立节点。

3) Neo4j 实现与 Mock 的兼容

- `replace/neo4j_graph_database.py` 实现了一个面向 Neo4j 驱动的客户端，尽量对外提供与 `replace` 中期望的 `MockGraphDB` 接口兼容的属性和方法（`nodes`, `edges`, `add_node`, `add_edge`, `get_node`, `update_edge`, `delete_node` 等）。
- 在无法直接通过边 id 在 Neo4j 中进行查找/修改的场景，`update_edge` 提供了可行的替代实现（通过匹配 source/target id 重新创建关系或在关系属性中使用 edge_id 作为标识）。

## 关键代码节选

下面节选出仓库中最关键的实现片段，帮助快速定位代码逻辑。

1) `modelscope_agent/environment/graph_database/build.py` — C 分支核心（节选）

```python
# --- C 分支：动态导入 replace 实现并运行 C 分析器
if language and language.lower() == 'c':
    import sys, json
    from pathlib import Path
    repo_root = Path(__file__).resolve().parents[3]
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))
    replace_dir = repo_root.joinpath('replace')
    if str(replace_dir) not in sys.path:
        sys.path.insert(0, str(replace_dir))

    # 从 setting.json 读取 Neo4j 配置
    setting_path = repo_root / 'apps' / 'codexgraph_agent' / 'setting.json'
    try:
        with open(setting_path, 'r', encoding='utf-8') as f:
            settings = json.load(f)
            neo4j_settings = settings['setting']['neo4j']
    except Exception:
        neo4j_settings = {...}

    # 适配主项目图 DB 到 replace 子模块期望的 API
    class ReplaceGraphDBAdapter:
        def __init__(self, graphdb_handler, task_id):
            self._g = graphdb_handler
            self._task_id = task_id
        def add_node(self, label=None, full_name=None, parms=None, **kwargs):
            return self._g.add_node(label, full_name, parms)
        def add_edge(self, start_label=None, start_name=None, relationship_type=None, end_label=None, end_name=None, params=None, **kwargs):
            return self._g.add_edge(start_label, start_name, relationship_type, end_label, end_name, params)
        # ... get_node / update_edge / delete_node / nodes / edges 实现 ...

    # 导入 replace 模块并执行 AST 遍历写入
    from ast_visitor_client import AstVisitorClient
    from c_ast_traverser import traverse_c_ast_and_record

    file_list = find_source_files(repo_path)  # 查找 *.c / *.h 等
    client = AstVisitorClient(adapter, task_root_path=repo_path)
    for i, file_path in enumerate(sorted(file_list)):
        traverse_c_ast_and_record(client, file_path)
    client.post_process_references()
```

## 如何运行与验证

1. 在 web UI 中（或 `apps/codexgraph_agent/setting.json`），把 `language` 设置为 `C`。例如把 `apps/codexgraph_agent/setting.json` 中 `setting.language` 改为 `"C"`。
2. 在 UI 中点击 Build 按钮，它会调用` build_graph_database(..., language='C')`
3. `replace/` 下也提供独立运行脚本 `main.py` 与 `test_neo4j_connection.py`，可用于离线测试 C 分析器与 Neo4j 的连通性：

```powershell
cd replace
pip install -r requirements.txt
python test_neo4j_connection.py
# 成功后（或在独立测试环境下）运行：
python main.py <repo_path> --use-neo4j --neo4j-password <pwd> --clear-db
```

