"""
测试 Neo4j 连接的简单脚本
用于验证 Neo4j 是否正确安装和配置
"""

import sys
from neo4j_graph_database import Neo4jGraphDatabase

def test_connection():
    """测试 Neo4j 数据库连接"""
    
    print("=" * 60)
    print("Neo4j 连接测试")
    print("=" * 60)
    
    # 提示用户输入密码
    password = input("\n请输入 Neo4j 密码 (默认: password): ").strip()
    if not password:
        password = "password"
    
    uri = input("请输入 Neo4j URI (默认: bolt://localhost:7687): ").strip()
    if not uri:
        uri = "bolt://localhost:7687"
    
    try:
        print(f"\n正在连接到 Neo4j: {uri}")
        db = Neo4jGraphDatabase(
            uri=uri,
            user="neo4j",
            password=password
        )
        
        print("\n✓ 连接成功！")
        
        # 测试基本操作
        print("\n--- 测试基本操作 ---")
        
        # 1. 清空数据库
        print("1. 清空测试数据...")
        db.clear_database()
        
        # 2. 创建索引
        print("2. 创建索引...")
        db.create_indexes()
        
        # 3. 添加测试节点
        print("3. 添加测试节点...")
        db.add_node("test_repo", "REPOSITORY", {"name": "test_repo", "path": "/test"})
        db.add_node("test_file.c", "FILE", {"name": "test_file.c", "path": "test_file.c"})
        db.add_node("test_function", "FUNCTION", {
            "name": "test_function",
            "full_name": "test_file.c.test_function",
            "signature": "int (int x, int y)"
        })
        
        # 4. 添加测试边
        print("4. 添加测试关系...")
        db.add_edge("test_repo", "CONTAINS_FILE", "test_file.c")
        db.add_edge("test_file.c", "CONTAINS", "test_function")
        
        # 5. 查询统计
        print("\n5. 查询数据库统计...")
        stats = db.get_statistics()
        print(f"\n   总节点数: {stats['total_nodes']}")
        print(f"   总关系数: {stats['total_relationships']}")
        print(f"   按类型统计:")
        for node_type, count in stats['nodes_by_type'].items():
            print(f"     - {node_type}: {count}")
        
        # 6. 执行自定义查询
        print("\n6. 执行自定义查询...")
        results = db.execute_query("""
            MATCH (n)
            RETURN n.name, n.type
            ORDER BY n.name
        """)
        print(f"   查询结果：")
        for record in results:
            print(f"     - {record['n.name']} ({record['n.type']})")
        
        # 7. 清理测试数据
        print("\n7. 清理测试数据...")
        db.clear_database()
        
        print("\n" + "=" * 60)
        print("✓ 所有测试通过！Neo4j 已正确配置。")
        print("=" * 60)
        print("\n你现在可以使用以下命令分析代码库：")
        print(f"  python main.py <repo_path> --use-neo4j --neo4j-password {password}")
        print("\n")
        
        # 关闭连接
        db.close()
        return True
        
    except Exception as e:
        print(f"\n✗ 连接失败: {e}")
        print("\n请检查：")
        print("  1. Neo4j 服务是否正在运行")
        print("  2. URI 和端口是否正确")
        print("  3. 用户名和密码是否正确")
        print("  4. 防火墙是否阻止了连接")
        return False

if __name__ == "__main__":
    success = test_connection()
    sys.exit(0 if success else 1)

