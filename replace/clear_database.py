#!/usr/bin/env python3
"""
清空 Neo4j 数据或重建数据库的脚本
"""

import argparse
from neo4j_graph_database import Neo4jGraphDatabase


def clear_database_all(uri: str, user: str, password: str, database: str) -> None:
    """删除所有关系与节点，并尝试删除所有索引和约束（保留数据库与标签/属性键令牌）。"""
    db = Neo4jGraphDatabase(uri=uri, user=user, password=password, database=database)

    try:
        print("正在完全清空数据库中的数据...")

        stats_before = db.get_statistics()
        print(f"清空前 - 节点数: {stats_before['total_nodes']}, 关系数: {stats_before['total_relationships']}")

        with db.driver.session(database=database) as session:
            # 1) 关系
            print("正在删除所有关系...")
            result = session.run("MATCH ()-[r]->() DELETE r")
            print(f"已删除 {result.consume().counters.relationships_deleted} 个关系")

            # 2) 节点
            print("正在删除所有节点...")
            result = session.run("MATCH (n) DELETE n")
            print(f"已删除 {result.consume().counters.nodes_deleted} 个节点")

            # 3) 索引
            print("正在删除所有索引...")
            try:
                for record in session.run("SHOW INDEXES"):
                    index_name = record.get("name")
                    if not index_name:
                        continue
                    try:
                        session.run(f"DROP INDEX {index_name}")
                        print(f"已删除索引: {index_name}")
                    except Exception as e:
                        print(f"删除索引 {index_name} 时出错: {e}")
            except Exception as e:
                print(f"获取索引列表时出错: {e}")

            # 4) 约束
            print("正在删除所有约束...")
            try:
                for record in session.run("SHOW CONSTRAINTS"):
                    constraint_name = record.get("name")
                    if not constraint_name:
                        continue
                    try:
                        session.run(f"DROP CONSTRAINT {constraint_name}")
                        print(f"已删除约束: {constraint_name}")
                    except Exception as e:
                        print(f"删除约束 {constraint_name} 时出错: {e}")
            except Exception as e:
                print(f"获取约束列表时出错: {e}")

        stats_after = db.get_statistics()
        print(f"清空后 - 节点数: {stats_after['total_nodes']}, 关系数: {stats_after['total_relationships']}")
        print("✅ 数据清空完成（标签/关系类型/属性键令牌仍会保留）。")

    except Exception as e:
        print(f"❌ 清空数据库数据时出错: {e}")
    finally:
        db.close()


def recreate_database(uri: str, user: str, password: str, database: str) -> None:
    """重建数据库：在 system 数据库中 DROP 并 CREATE 指定数据库。

    注意：这会彻底移除所有数据、索引、约束，以及标签/关系类型/属性键令牌。
    需要具有管理员权限。
    """
    print(f"正在重建数据库 `{database}` ...")
    # 复用 Neo4jGraphDatabase 的驱动以避免直接依赖外部导入
    db = Neo4jGraphDatabase(uri=uri, user=user, password=password, database=database)
    try:
        with db.driver.session(database="system") as sys_sess:
            sys_sess.run(f"DROP DATABASE {database} IF EXISTS")
            sys_sess.run(f"CREATE DATABASE {database} IF NOT EXISTS")
            sys_sess.run(f"START DATABASE {database}")
        print("✅ 数据库重建完成。")
    except Exception as e:
        print(f"❌ 重建数据库时出错: {e}")
    finally:
        db.close()


def main():
    parser = argparse.ArgumentParser(description="清空 Neo4j 数据或重建数据库")
    parser.add_argument("--uri", default="bolt://localhost:7687", help="Neo4j URI")
    parser.add_argument("--user", default="neo4j", help="Neo4j 用户名")
    parser.add_argument("--password", default="neo4j1231", help="Neo4j 密码")
    parser.add_argument("--database", default="neo4j", help="数据库名")
    parser.add_argument("--recreate-db", action="store_true", help="重建数据库而不是仅清空数据")

    args = parser.parse_args()

    if args.recreate_db:
        recreate_database(args.uri, args.user, args.password, args.database)
    else:
        clear_database_all(args.uri, args.user, args.password, args.database)


if __name__ == "__main__":
    main()
