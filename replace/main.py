# c_code_analyzer/main.py

import os
import argparse 

from mock_dependencies import MockGraphDB
from neo4j_graph_database import Neo4jGraphDatabase
from ast_visitor_client import AstVisitorClient
from c_ast_traverser import traverse_c_ast_and_record

def find_source_files(base_dir, extensions=['.c', '.cpp', '.h', '.hpp']):
    source_files = []
    for root, _, files in os.walk(base_dir):
        for file in files:
            if any(file.endswith(ext) for ext in extensions):
                source_files.append(os.path.join(root, file))
    return source_files

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="Analyze a C/C++ code repository and build a dependency graph.")
    parser.add_argument("repo_path", type=str, 
                        help="Path to the code repository to analyze.")
    parser.add_argument("--extensions", nargs='*', default=['.c', '.cpp', '.h', '.hpp'],
                        help="List of file extensions to include in the analysis (e.g., .c .h).")
    parser.add_argument("--use-neo4j", action='store_true',
                        help="Use real Neo4j database instead of mock database.")
    parser.add_argument("--neo4j-uri", type=str, default="bolt://localhost:7687",
                        help="Neo4j database URI (default: bolt://localhost:7687).")
    parser.add_argument("--neo4j-user", type=str, default="neo4j",
                        help="Neo4j username (default: neo4j).")
    parser.add_argument("--neo4j-password", type=str, default="password",
                        help="Neo4j password (default: password).")
    parser.add_argument("--neo4j-database", type=str, default="neo4j",
                        help="Neo4j database name (default: neo4j).")
    parser.add_argument("--clear-db", action='store_true',
                        help="Clear the database before analysis.")

    args = parser.parse_args()

    repo_path = os.path.abspath(args.repo_path) 
    if not os.path.isdir(repo_path):
        print(f"Error: Repository path '{repo_path}' is not a valid directory.")
        exit(1)

    print(f"--- 准备分析代码库: {repo_path} ---")

    # 根据参数选择使用 Neo4j 或 Mock 数据库
    if args.use_neo4j:
        print(f"使用真实 Neo4j 数据库: {args.neo4j_uri}")
        graph_db = Neo4jGraphDatabase(
            uri=args.neo4j_uri,
            user=args.neo4j_user,
            password=args.neo4j_password,
            database=args.neo4j_database
        )
        
        # 如果需要，清空数据库
        if args.clear_db:
            print("清空数据库...")
            graph_db.clear_database()
        
        # 创建索引
        graph_db.create_indexes()
    else:
        print("使用模拟数据库 (MockGraphDB)")
        graph_db = MockGraphDB()
    
    client = AstVisitorClient(graph_db, task_root_path=repo_path)

    source_files = find_source_files(repo_path, args.extensions)
    if not source_files:
        print(f"No source files found with extensions {args.extensions} in {repo_path}")
        exit(0)

    print(f"找到 {len(source_files)} 个源文件进行分析。")

    # 对文件进行排序，可能有助于先处理头文件或定义文件，但这并非严格要求
    # 真正的符号解析通常需要多次遍历或更复杂的构建过程
    source_files.sort() 

    for i, file_path in enumerate(source_files):
        traverse_c_ast_and_record(client, file_path)
    
    # === 新增：在所有文件分析完成后调用后处理阶段 ===
    client.post_process_references()

    # 4. 打印最终的符号数据
    print("\n--- 最终记录的符号数据片段 ---")
    # 过滤掉内部/虚拟符号
    filtered_symbols = {
        name: data for name, data in client.symbol_data.items() 
        if name not in ['builtins', 'code_repository_root']
    }

    # 按照 kind 和 full_name 排序，使得输出更易读
    sorted_symbols = sorted(filtered_symbols.items(), key=lambda item: (item[1].get('kind', 'UNKNOWN'), item[0]))

    for full_name, data in sorted_symbols:
        signature_str = f" | Signature: {data['signature']}" if 'signature' in data else ""
        print(f"  {data.get('kind', 'UNKNOWN'):<22} | {full_name} (Parent: {data.get('parent_name', '')}){signature_str}")

    print("\n--- 全局定义映射 ---")
    for short_name, full_name in client.global_symbol_definitions.items():
        print(f"  {short_name:<15} -> {full_name}")
    
    # 如果使用 Neo4j，显示数据库统计信息并关闭连接
    if args.use_neo4j:
        print("\n--- Neo4j 数据库统计 ---")
        stats = graph_db.get_statistics()
        print(f"  总节点数: {stats['total_nodes']}")
        print(f"  总关系数: {stats['total_relationships']}")
        print(f"  按类型统计节点:")
        for node_type, count in sorted(stats['nodes_by_type'].items(), key=lambda x: x[1], reverse=True):
            print(f"    {node_type:<22}: {count}")
        
        # 关闭数据库连接
        graph_db.close()
        print("\n✓ 分析完成，Neo4j 连接已关闭")