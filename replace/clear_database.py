#!/usr/bin/env python3
"""
清空Neo4j数据库的脚本
"""

from neo4j_graph_database import Neo4jGraphDatabase

def clear_database():
    """完全清空Neo4j数据库，包括所有节点、关系、索引和约束"""
    
    # 连接到Neo4j数据库
    db = Neo4jGraphDatabase(
        uri="bolt://localhost:7687",
        user="neo4j", 
        password="neo4j1231"  # 请根据你的实际密码修改
    )
    
    try:
        print("正在完全清空数据库...")
        
        # 获取清空前的统计信息
        stats_before = db.get_statistics()
        print(f"清空前 - 节点数: {stats_before['total_nodes']}, 关系数: {stats_before['total_relationships']}")
        
        with db.driver.session(database=db.database) as session:
            # 1. 删除所有关系
            print("正在删除所有关系...")
            result = session.run("MATCH ()-[r]->() DELETE r")
            print(f"已删除 {result.consume().counters.relationships_deleted} 个关系")
            
            # 2. 删除所有节点
            print("正在删除所有节点...")
            result = session.run("MATCH (n) DELETE n")
            print(f"已删除 {result.consume().counters.nodes_deleted} 个节点")
            
            # 3. 删除所有索引
            print("正在删除所有索引...")
            try:
                # 获取所有索引
                indexes_result = session.run("SHOW INDEXES")
                indexes = [record["name"] for record in indexes_result]
                
                for index_name in indexes:
                    try:
                        session.run(f"DROP INDEX {index_name}")
                        print(f"已删除索引: {index_name}")
                    except Exception as e:
                        print(f"删除索引 {index_name} 时出错: {e}")
            except Exception as e:
                print(f"获取索引列表时出错: {e}")
            
            # 4. 删除所有约束
            print("正在删除所有约束...")
            try:
                # 获取所有约束
                constraints_result = session.run("SHOW CONSTRAINTS")
                constraints = [record["name"] for record in constraints_result]
                
                for constraint_name in constraints:
                    try:
                        session.run(f"DROP CONSTRAINT {constraint_name}")
                        print(f"已删除约束: {constraint_name}")
                    except Exception as e:
                        print(f"删除约束 {constraint_name} 时出错: {e}")
            except Exception as e:
                print(f"获取约束列表时出错: {e}")
        
        # 获取清空后的统计信息
        stats_after = db.get_statistics()
        print(f"清空后 - 节点数: {stats_after['total_nodes']}, 关系数: {stats_after['total_relationships']}")
        
        print("✅ 数据库完全清空完成！所有节点、关系、索引和约束已删除。")
        
    except Exception as e:
        print(f"❌ 清空数据库时出错: {e}")
    finally:
        db.close()

if __name__ == "__main__":
    clear_database()
