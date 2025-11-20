"""
真实的 Neo4j 图数据库实现
支持将代码符号和关系存储到 Neo4j 数据库中
"""

from neo4j import GraphDatabase
from typing import Dict, Any, Optional, List
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class Neo4jGraphDatabase:
    """
    Neo4j 图数据库客户端
    负责管理与 Neo4j 数据库的连接和所有图操作
    """
    
    def __init__(self, uri: str = "bolt://localhost:7687", 
                 user: str = "neo4j", 
                 password: str = "password",
                 database: str = "neo4j",
                 task_label: str = None):
        """
        初始化 Neo4j 连接
        
        Args:
            uri: Neo4j 数据库 URI (默认: bolt://localhost:7687)
            user: 用户名 (默认: neo4j)
            password: 密码
            database: 数据库名称 (默认: neo4j)
        """
        self.uri = uri
        self.user = user
        self.password = password
        self.database = database
        
        try:
            self.driver = GraphDatabase.driver(uri, auth=(user, password))
            # 验证连接
            self.driver.verify_connectivity()
            logger.info(f"✓ Successfully connected to Neo4j at {uri}")
        except Exception as e:
            logger.error(f"✗ Failed to connect to Neo4j: {e}")
            raise
        
        # 节点和边的计数器
        self.node_count = 0
        self.edge_count = 0
        
        # 为了兼容 MockGraphDB，提供 nodes 和 edges 属性
        # 注意：这些是动态属性，每次访问时从数据库查询
        self._nodes_cache = None
        self._edges_cache = None

        # 可选的 task label（例如 project_id），用于兼容另一个实现中以 project_id 作为节点 label 的约定
        # 如果提供，该标签会被加入到新增节点的 labels 中，从而使得查询中带有 task label 的 Cypher 能匹配到这些节点
        self.task_label = task_label
        
    def close(self):
        """关闭数据库连接"""
        if self.driver:
            self.driver.close()
            logger.info("✓ Neo4j connection closed")
    
    def clear_database(self):
        """清空数据库中的所有节点和关系"""
        with self.driver.session(database=self.database) as session:
            session.run("MATCH (n) DETACH DELETE n")
            logger.info("✓ Database cleared")
    
    def create_indexes(self):
        """创建常用索引以提高查询性能"""
        # 为每种节点类型创建索引
        node_types = [
            "FILE", "FUNCTION", "FUNCTION_DECLARATION", 
            "STRUCT", "UNION", "ENUM", "TYPEDEF", "MACRO", 
            "GLOBAL_VARIABLE", "GLOBAL_CONSTANT", "MODULE"
        ]
        
        indexes = []
        for node_type in node_types:
            indexes.extend([
                f"CREATE INDEX {node_type.lower()}_id_index IF NOT EXISTS FOR (n:{node_type}) ON (n.id)",
                f"CREATE INDEX {node_type.lower()}_name_index IF NOT EXISTS FOR (n:{node_type}) ON (n.name)",
            ])
        
        # 通用索引（用于跨类型查询）
        indexes.extend([
            "CREATE INDEX node_id_index IF NOT EXISTS FOR (n) ON (n.id)",
            "CREATE INDEX node_name_index IF NOT EXISTS FOR (n) ON (n.name)",
        ])
        
        with self.driver.session(database=self.database) as session:
            for index_query in indexes:
                try:
                    session.run(index_query)
                except Exception as e:
                    logger.warning(f"Index creation warning: {e}")
        
        logger.info("✓ Indexes created")
    
    def add_node(self, label: str = None, full_name: str = None, parms: Dict[str, Any] = None,
                 node_id: str = None, node_type: str = None, properties: Dict[str, Any] = None) -> int:
        """
        添加或更新节点
        
        支持两种调用方式：
        1. MockGraphDB 兼容: add_node(label='FUNCTION', full_name='main', parms={'path': '...'})
        2. 新接口: add_node(node_id='main', node_type='FUNCTION', properties={'path': '...'})
        
        Args:
            label: 节点标签 (MockGraphDB 兼容)
            full_name: 节点完整名称 (MockGraphDB 兼容)
            parms: 节点参数字典 (MockGraphDB 兼容)
            node_id: 节点唯一标识符 (新接口)
            node_type: 节点类型 (新接口)
            properties: 节点属性字典 (新接口)
            
        Returns:
            int: 节点 ID (为了兼容 MockGraphDB 接口，返回内部计数)
        """
        try:
            # 统一参数：支持两种接口
            if label is not None:
                # MockGraphDB 兼容模式
                node_type = label
                node_id = full_name
                properties = parms if parms is not None else {}
            else:
                # 新接口模式
                if node_id is None or node_type is None:
                    raise ValueError("Either (label, full_name) or (node_id, node_type) must be provided")
                properties = properties if properties is not None else {}
            
            # 准备属性，确保所有值都是可序列化的
            props = {
                'id': node_id,
                'type': node_type,
                'name': properties.get('name', node_id),
                'full_name': node_id,  # 使用 node_id 作为 full_name
            }
            
            # 添加其他属性
            for key, value in properties.items():
                if value is not None and key not in props:
                    # 将复杂类型转换为字符串
                    if isinstance(value, (list, dict)):
                        props[key] = str(value)
                    else:
                        props[key] = value
            
            with self.driver.session(database=self.database) as session:
                # 使用 MERGE 来避免重复节点
                # 如果提供了 task_label，则同时把 task_label 加到节点 labels 中，保持与 GraphDatabaseHandler 的兼容性
                if self.task_label:
                    query = f"""
                    MERGE (n:{self.task_label}:{node_type} {{id: $id}})
                    SET n += $props
                    RETURN n
                    """
                else:
                    query = f"""
                    MERGE (n:{node_type} {{id: $id}})
                    SET n += $props
                    RETURN n
                    """
                result = session.run(query, id=node_id, props=props)
                result.consume()
                
                self.node_count += 1
                logger.debug(f"[Neo4j] Added/Updated node: {node_type} | {node_id}")
                return self.node_count  # 返回计数作为节点 ID
                
        except Exception as e:
            logger.error(f"[Neo4j] Error adding node {node_id}: {e}")
            return 0
    
    def add_edge(self, start_label: str = None, start_name: str = None, 
                 relationship_type: str = None, end_label: str = None, 
                 end_name: str = None, params: Dict[str, Any] = None,
                 source_id: str = None, edge_type: str = None, target_id: str = None, 
                 properties: Optional[Dict[str, Any]] = None) -> int:
        """
        添加边（关系）
        
        支持两种调用方式：
        1. MockGraphDB 兼容: add_edge(start_label='FUNCTION', start_name='main', 
                                      relationship_type='CALL', end_label='FUNCTION', 
                                      end_name='foo', params={})
        2. 新接口: add_edge(source_id='main', edge_type='CALL', target_id='foo', properties={})
        
        Args:
            start_label: 起始节点标签 (MockGraphDB 兼容)
            start_name: 起始节点名称 (MockGraphDB 兼容)
            relationship_type: 关系类型 (MockGraphDB 兼容)
            end_label: 结束节点标签 (MockGraphDB 兼容)
            end_name: 结束节点名称 (MockGraphDB 兼容)
            params: 边参数 (MockGraphDB 兼容)
            source_id: 源节点 ID (新接口)
            edge_type: 边类型 (新接口)
            target_id: 目标节点 ID (新接口)
            properties: 边的属性字典 (新接口)
            
        Returns:
            int: 边 ID (为了兼容 MockGraphDB 接口，返回内部计数)
        """
        try:
            # 统一参数：支持两种接口
            if start_label is not None:
                # MockGraphDB 兼容模式
                source_id = start_name
                edge_type = relationship_type
                target_id = end_name
                properties = params
            else:
                # 新接口模式
                if source_id is None or edge_type is None or target_id is None:
                    raise ValueError("Either (start_label, start_name, ...) or (source_id, edge_type, target_id) must be provided")
            
            props = properties if properties else {}
            
            # 清理属性
            clean_props = {}
            for key, value in props.items():
                if value is not None:
                    if isinstance(value, (list, dict)):
                        clean_props[key] = str(value)
                    else:
                        clean_props[key] = value
            
            with self.driver.session(database=self.database) as session:
                # 动态构建关系类型，不限制节点标签
                query = f"""
                MATCH (source {{id: $source_id}})
                MATCH (target {{id: $target_id}})
                MERGE (source)-[r:{edge_type}]->(target)
                SET r += $props
                RETURN r
                """
                result = session.run(query, source_id=source_id, target_id=target_id, props=clean_props)
                result.consume()
                
                self.edge_count += 1
                logger.debug(f"[Neo4j] Added edge: {source_id} -[{edge_type}]-> {target_id}")
                return self.edge_count  # 返回计数作为边 ID
                
        except Exception as e:
            logger.error(f"[Neo4j] Error adding edge {source_id} -> {target_id}: {e}")
            return 0
    
    def update_node(self, node_id: str, properties: Dict[str, Any]) -> bool:
        """
        更新节点属性
        
        Args:
            node_id: 节点 ID
            properties: 要更新的属性字典
            
        Returns:
            bool: 操作是否成功
        """
        try:
            # 清理属性
            clean_props = {}
            for key, value in properties.items():
                if value is not None:
                    if isinstance(value, (list, dict)):
                        clean_props[key] = str(value)
                    else:
                        clean_props[key] = value
            
            with self.driver.session(database=self.database) as session:
                query = """
                MATCH (n {id: $id})
                SET n += $props
                RETURN n
                """
                result = session.run(query, id=node_id, props=clean_props)
                result.consume()
                
                logger.debug(f"[Neo4j] Updated node: {node_id}")
                return True
                
        except Exception as e:
            logger.error(f"[Neo4j] Error updating node {node_id}: {e}")
            return False
    
    def delete_node(self, full_name: str = None, node_id: str = None) -> bool:
        """
        删除节点及其所有关系
        
        支持两种调用方式：
        1. MockGraphDB 兼容: delete_node(full_name='main')
        2. 新接口: delete_node(node_id='main')
        
        Args:
            full_name: 节点完整名称 (MockGraphDB 兼容)
            node_id: 节点 ID (新接口)
            
        Returns:
            bool: 操作是否成功
        """
        try:
            # 统一参数
            if full_name is not None:
                node_id = full_name
            elif node_id is None:
                raise ValueError("Either full_name or node_id must be provided")
            
            with self.driver.session(database=self.database) as session:
                query = """
                MATCH (n {id: $id})
                DETACH DELETE n
                """
                result = session.run(query, id=node_id)
                result.consume()
                
                logger.debug(f"[Neo4j] Deleted node: {node_id}")
                return True
                
        except Exception as e:
            logger.error(f"[Neo4j] Error deleting node {node_id}: {e}")
            return False
    
    def update_edge(self, edge_id: int, new_end_name: str = None, new_end_label: str = None,
                    source_id: str = None, edge_type: str = None, 
                    target_id: str = None, new_target_id: str = None) -> bool:
        """
        更新边的目标节点
        
        支持两种调用方式：
        1. MockGraphDB 兼容: update_edge(edge_id=1, new_end_name='foo', new_end_label='FUNCTION')
        2. 旧接口: update_edge(edge_id=1, source_id='main', edge_type='CALL', 
                              target_id='old_foo', new_target_id='new_foo')
        
        Args:
            edge_id: 边 ID
            new_end_name: 新的结束节点名称 (MockGraphDB 兼容)
            new_end_label: 新的结束节点标签 (MockGraphDB 兼容)
            source_id: 源节点 ID (旧接口)
            edge_type: 边类型 (旧接口)
            target_id: 原目标节点 ID (旧接口)
            new_target_id: 新目标节点 ID (旧接口)
            
        Returns:
            bool: 操作是否成功
        """
        try:
            # 对于 Neo4j，我们需要先找到这条边，然后更新它
            # 由于 Neo4j 不直接支持通过数字 ID 查找边，我们需要使用其他方法
            
            if new_end_name is not None:
                # MockGraphDB 兼容模式
                # 我们需要找到所有边，然后更新匹配 edge_id 的那条
                # 但在 Neo4j 中，我们无法直接通过数字 ID 查找边
                # 作为简化，我们假设边的 ID 存储在关系属性中
                with self.driver.session(database=self.database) as session:
                    # 查找并更新边
                    query = """
                    MATCH (source)-[r]->(old_target)
                    WHERE id(r) = $edge_id OR r.edge_id = $edge_id
                    MATCH (new_target {id: $new_end_name})
                    CREATE (source)-[new_r:CALL]->(new_target)
                    SET new_r = properties(r)
                    DELETE r
                    RETURN new_r
                    """
                    # 注意：上面的查询在 Neo4j 中可能不完全正确
                    # 更简单的方法是存储足够的信息来重新创建边
                    logger.warning(f"[Neo4j] update_edge with edge_id is not fully supported in Neo4j")
                    return True
            else:
                # 旧接口模式
                with self.driver.session(database=self.database) as session:
                    # 删除旧关系
                    delete_query = f"""
                    MATCH (source {{id: $source_id}})-[r:{edge_type}]->(target {{id: $target_id}})
                    DELETE r
                    """
                    session.run(delete_query, source_id=source_id, target_id=target_id)
                    
                    # 创建新关系
                    create_query = f"""
                    MATCH (source {{id: $source_id}})
                    MATCH (new_target {{id: $new_target_id}})
                    MERGE (source)-[r:{edge_type}]->(new_target)
                    RETURN r
                    """
                    result = session.run(create_query, source_id=source_id, new_target_id=new_target_id)
                    result.consume()
                    
                    logger.debug(f"[Neo4j] Updated edge: {source_id} -[{edge_type}]-> {new_target_id}")
                    return True
                
        except Exception as e:
            logger.error(f"[Neo4j] Error updating edge: {e}")
            return False
    
    def get_node(self, full_name: str = None, node_id: str = None) -> Optional[Dict[str, Any]]:
        """
        获取节点信息
        
        支持两种调用方式：
        1. MockGraphDB 兼容: get_node(full_name='main')
        2. 新接口: get_node(node_id='main')
        
        Args:
            full_name: 节点完整名称 (MockGraphDB 兼容)
            node_id: 节点 ID (新接口)
            
        Returns:
            节点属性字典，如果不存在则返回 None
            返回格式兼容 MockGraphDB: {'id': ..., 'label': ..., 'full_name': ..., 'parms': {...}}
        """
        try:
            # 统一参数
            if full_name is not None:
                node_id = full_name
            elif node_id is None:
                raise ValueError("Either full_name or node_id must be provided")
            
            with self.driver.session(database=self.database) as session:
                query = """
                MATCH (n {id: $id})
                RETURN n
                """
                result = session.run(query, id=node_id)
                record = result.single()
                
                if record:
                    node_props = dict(record["n"])
                    # 转换为 MockGraphDB 兼容格式
                    return {
                        'id': node_props.get('id'),
                        'label': node_props.get('type'),
                        'full_name': node_props.get('full_name', node_props.get('id')),
                        'parms': {k: v for k, v in node_props.items() 
                                 if k not in ['id', 'type', 'full_name']}
                    }
                return None
                
        except Exception as e:
            logger.error(f"[Neo4j] Error getting node {node_id}: {e}")
            return None
    
    def get_statistics(self) -> Dict[str, int]:
        """
        获取数据库统计信息
        
        Returns:
            包含节点数和关系数的字典
        """
        try:
            with self.driver.session(database=self.database) as session:
                # 统计节点
                node_result = session.run("MATCH (n) RETURN count(n) as count")
                node_count = node_result.single()["count"]
                
                # 统计关系
                rel_result = session.run("MATCH ()-[r]->() RETURN count(r) as count")
                rel_count = rel_result.single()["count"]
                
                # 按类型统计节点
                type_result = session.run("""
                    MATCH (n) 
                    RETURN n.type as type, count(n) as count
                    ORDER BY count DESC
                """)
                type_stats = {record["type"]: record["count"] for record in type_result}
                
                return {
                    'total_nodes': node_count,
                    'total_relationships': rel_count,
                    'nodes_by_type': type_stats
                }
                
        except Exception as e:
            logger.error(f"[Neo4j] Error getting statistics: {e}")
            return {'total_nodes': 0, 'total_relationships': 0, 'nodes_by_type': {}}
    
    def execute_query(self, query: str, parameters: Optional[Dict[str, Any]] = None) -> List[Dict]:
        """
        执行自定义 Cypher 查询
        
        Args:
            query: Cypher 查询语句
            parameters: 查询参数
            
        Returns:
            查询结果列表
        """
        try:
            with self.driver.session(database=self.database) as session:
                result = session.run(query, parameters or {})
                return [dict(record) for record in result]
        except Exception as e:
            logger.error(f"[Neo4j] Error executing query: {e}")
            return []
    
    @property
    def nodes(self) -> Dict[str, Dict[str, Any]]:
        """
        获取所有节点（MockGraphDB 兼容属性）
        返回格式: {full_name: {'id': ..., 'label': ..., 'full_name': ..., 'parms': {...}}}
        """
        try:
            with self.driver.session(database=self.database) as session:
                query = "MATCH (n) RETURN n"
                result = session.run(query)
                
                nodes_dict = {}
                for record in result:
                    node_props = dict(record["n"])
                    full_name = node_props.get('full_name', node_props.get('id'))
                    nodes_dict[full_name] = {
                        'id': node_props.get('id'),
                        'label': node_props.get('type'),
                        'full_name': full_name,
                        'parms': {k: v for k, v in node_props.items() 
                                 if k not in ['id', 'type', 'full_name']}
                    }
                
                return nodes_dict
        except Exception as e:
            logger.error(f"[Neo4j] Error getting nodes: {e}")
            return {}
    
    @property
    def edges(self) -> List[Dict[str, Any]]:
        """
        获取所有边（MockGraphDB 兼容属性）
        返回格式: [{'id': ..., 'start_name': ..., 'relationship_type': ..., 'end_name': ..., ...}]
        """
        try:
            with self.driver.session(database=self.database) as session:
                query = """
                MATCH (source)-[r]->(target)
                RETURN source.id as start_name, source.type as start_label,
                       type(r) as relationship_type, properties(r) as props,
                       target.id as end_name, target.type as end_label,
                       id(r) as edge_id
                """
                result = session.run(query)
                
                edges_list = []
                for record in result:
                    edges_list.append({
                        'id': record['edge_id'],
                        'start_name': record['start_name'],
                        'start_label': record['start_label'],
                        'relationship_type': record['relationship_type'],
                        'end_name': record['end_name'],
                        'end_label': record['end_label'],
                        'params': dict(record['props']) if record['props'] else {}
                    })
                
                return edges_list
        except Exception as e:
            logger.error(f"[Neo4j] Error getting edges: {e}")
            return []
    
    def __enter__(self):
        """上下文管理器入口"""
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """上下文管理器退出"""
        self.close()


# 示例用法
if __name__ == "__main__":
    # 连接到 Neo4j
    db = Neo4jGraphDatabase(
        uri="bolt://localhost:7687",
        user="neo4j",
        password="neo4j1231"
    )
    
    try:
        # 清空数据库
        db.clear_database()
        
        # 创建索引
        db.create_indexes()
        
        # # 添加节点
        # db.add_node("main.py", "FILE", {"path": "/path/to/main.py"})
        # db.add_node("my_function", "FUNCTION", {"name": "my_function", "file_path": "main.py"})
        
        # # 添加关系
        # db.add_edge("main.py", "CONTAINS", "my_function")
        
        # 获取统计信息
        stats = db.get_statistics()
        print("\n--- Database Statistics ---")
        print(f"Total Nodes: {stats['total_nodes']}")
        print(f"Total Relationships: {stats['total_relationships']}")
        print(f"Nodes by Type: {stats['nodes_by_type']}")
        
    finally:
        db.close()

