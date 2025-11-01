# 方法描述生成器实现文档

## 概述

本文档详细说明了为实现智能方法描述生成功能（包含结构关系分析）所做的代码修改，以及如何扩展该功能。

---

## 功能目标

实现一个智能的方法描述生成器，能够：
1. 自动分析方法代码，生成简洁的中文描述
2. **分析节点周围的关系**（谁调用了我、我调用了谁、继承关系等）
3. 将关系信息融合到描述中，提供全局上下文
4. 集成到图数据库构建流程中，自动为METHOD节点生成描述

---

## 代码修改详情

### 1. `my_graph_db.py` - 添加关系查询功能

**修改位置**: 在 `GraphDatabaseHandler` 类中新增 `get_node_relations` 方法

**修改内容**:
```python
def get_node_relations(self, full_name):
    """获取某节点所有相关关系（出边+入边），返回结构化信息"""
    relations = {
        'incoming_calls': [],  # 谁调用了我
        'outgoing_calls': [],  # 我调用了谁
        'inherits_from': [],   # 我继承谁
        'inherited_by': [],    # 谁继承我
    }
    # 使用Cypher查询获取各种关系
    # ... 具体的Cypher查询代码
    return relations
```

**作用**: 
- 从Neo4j图数据库中查询指定节点的所有邻接关系
- 返回结构化的关系字典，包含调用关系和继承关系
- 为描述生成器提供结构上下文信息

**Cypher查询说明**:
- `incoming_calls`: 查询所有指向当前节点的CALL关系（谁调用了我）
- `outgoing_calls`: 查询所有从当前节点发出的CALL关系（我调用了谁）
- `inherits_from`: 查询当前节点的父类（继承关系）
- `inherited_by`: 查询继承当前节点的子类

---

### 2. `my_client.py` - 集成关系信息到描述生成流程

**修改位置**: `_generate_method_description` 方法

**修改前**:
```python
def _generate_method_description(self, full_name: str, data: dict) -> str:
    # ... 获取方法代码、方法名等信息
    description = description_generator.generate_method_description(
        method_code=method_code,
        method_name=method_name,
        class_name=class_name,
        file_path=file_path
    )
    return description
```

**修改后**:
```python
def _generate_method_description(self, full_name: str, data: dict) -> str:
    # ... 获取方法代码、方法名等信息
    
    # 新增：获取方法节点所有邻接关系
    relations = self.graphDB.get_node_relations(full_name)
    print(f"  关系信息: {relations}")
    
    # 将关系信息传递给描述生成器
    description = description_generator.generate_method_description(
        method_code=method_code,
        method_name=method_name,
        class_name=class_name,
        file_path=file_path,
        relations=relations  # 新增参数
    )
    return description
```

**作用**:
- 在生成描述前，自动从图数据库获取节点的所有关系信息
- 将关系信息传递给描述生成器，使其能够生成包含结构上下文的描述

**关键点**:
- 调用时机：在 `recordSymbolKind` 方法中，当处理METHOD/FUNCTION节点时调用
- 数据流：图数据库 → `get_node_relations` → `_generate_method_description` → 描述生成器

---

### 3. `method_description_generator.py` - 支持关系信息融合

#### 修改1: `generate_method_description` 方法签名

**修改前**:
```python
def generate_method_description(self, method_code: str, method_name: str, 
                                class_name: str = None, file_path: str = None) -> str:
```

**修改后**:
```python
def generate_method_description(self, method_code: str, method_name: str, 
                                class_name: str = None, file_path: str = None, 
                                relations: dict = None) -> str:
```

**作用**: 添加 `relations` 参数，支持接收结构关系信息

#### 修改2: `_build_prompt` 方法 - 融合关系信息到提示词

**修改前**:
```python
def _build_prompt(self, method_code: str, method_name: str, 
                 class_name: str = None, file_path: str = None) -> str:
    context_info = ""
    if class_name:
        context_info += f"所属类: {class_name}\n"
    if file_path:
        context_info += f"文件路径: {file_path}\n"
    
    prompt = f"""请分析以下Python方法..."""
    return prompt
```

**修改后**:
```python
def _build_prompt(self, method_code: str, method_name: str, 
                 class_name: str = None, file_path: str = None, 
                 relations: dict = None) -> str:
    context_info = ""
    if class_name:
        context_info += f"所属类: {class_name}\n"
    if file_path:
        context_info += f"文件路径: {file_path}\n"
    
    # 新增关系说明
    if relations:
        in_calls = relations.get('incoming_calls', [])
        out_calls = relations.get('outgoing_calls', [])
        inherited = relations.get('inherits_from', [])
        subed = relations.get('inherited_by', [])
        
        if in_calls:
            context_info += f"被以下方法调用: {', '.join(in_calls)[:200]}\n"
        if out_calls:
            context_info += f"调用了以下方法: {', '.join(out_calls)[:200]}\n"
        if inherited:
            context_info += f"继承自: {', '.join(inherited)[:100]}\n"
        if subed:
            context_info += f"被以下类继承: {', '.join(subed)[:100]}\n"
    
    # 更新prompt，要求分析关系
    prompt = f"""请分析以下Python方法及其结构关系，用简洁的中文描述它的作用、功能及关键关系：\n\n{context_info}方法名: {method_name}\n方法代码:\n```python\n{method_code}\n```\n请用一句话概括该方法的主要作用，并指出其与其它方法/类的重要关系（若有）：\n描述："""
    
    return prompt
```

**作用**:
- 将关系信息格式化为自然语言，添加到提示词的上下文部分
- 更新prompt模板，要求LLM分析并描述结构关系
- 限制关系列表长度，避免prompt过长

**关键设计决策**:
- 字符串截断：`[:200]` 和 `[:100]` 限制关系列表长度，避免超出token限制
- 条件渲染：只有当关系存在时才添加到context_info，保持提示词简洁

---

## 数据流程

```
图数据库构建流程:
┌─────────────────┐
│ recordSymbolKind│  创建METHOD节点
│ (my_client.py)  │
└────────┬────────┘
         │
         ▼
┌─────────────────────────┐
│ _generate_method_       │  1. 提取方法代码、名称等
│ description()           │  2. 调用 graphDB.get_node_relations()
│ (my_client.py)          │  3. 传递关系信息给描述生成器
└────────┬────────────────┘
         │
         ▼
┌─────────────────────────┐
│ get_node_relations()    │  执行Cypher查询，获取:
│ (my_graph_db.py)        │  - incoming_calls
│                         │  - outgoing_calls
│                         │  - inherits_from
│                         │  - inherited_by
└────────┬────────────────┘
         │
         ▼
┌─────────────────────────┐
│ generate_method_        │  1. 接收relations参数
│ description()           │  2. 调用 _build_prompt()
│ (method_description_   │  3. 调用 _call_llm()
│ generator.py)           │  4. 返回生成的描述
└────────┬────────────────┘
         │
         ▼
┌─────────────────────────┐
│ _build_prompt()         │  将关系信息格式化为prompt
│ (method_description_    │  示例输出:
│ generator.py)           │  "被以下方法调用: func1, func2
│                         │   调用了以下方法: math.log, utils.helper"
└────────┬────────────────┘
         │
         ▼
┌─────────────────────────┐
│ LLM API                 │  生成包含关系信息的描述
│ (大模型)                │  示例输出:
│                         │  "该方法用于计算数值，被module.foo
│                         │   调用，内部调用math.log进行对数运算"
└─────────────────────────┘
```

---

## 扩展指南

### 1. 添加新的关系类型

#### 步骤1: 扩展 `get_node_relations` 方法

在 `my_graph_db.py` 中添加新的关系查询：

```python
def get_node_relations(self, full_name):
    relations = {
        # ... 现有关系
        'new_relation_type': [],  # 新增关系类型
    }
    
    # 添加Cypher查询
    cypher = (
        "MATCH (src)-[r:NEW_RELATION_TYPE]->(dst {full_name: $full_name}) "
        "RETURN src.full_name AS related_node"
    )
    rs = self.execute_query(cypher, full_name=full_name)
    relations['new_relation_type'] = [r['related_node'] for r in rs if r.get('related_node')]
    
    return relations
```

**支持的关系类型**:
- `CALL`: 方法调用关系
- `INHERITS`: 继承关系
- `USES`: 使用关系（变量使用）
- `CONTAINS`: 包含关系（模块包含类/函数）
- 自定义关系类型...

#### 步骤2: 更新 `_build_prompt` 方法

在 `method_description_generator.py` 中添加新关系的格式化逻辑：

```python
def _build_prompt(self, ..., relations: dict = None) -> str:
    # ... 现有代码
    
    if relations:
        # 添加新关系的处理
        new_relations = relations.get('new_relation_type', [])
        if new_relations:
            context_info += f"新关系说明: {', '.join(new_relations)[:100]}\n"
    
    # ... 其余代码
```

---

### 2. 自定义描述风格

#### 修改提示词模板

在 `_build_prompt` 方法中修改prompt模板：

```python
prompt = f"""请用以下风格描述方法：
1. 使用专业术语
2. 突出方法的业务价值
3. 详细说明参数和返回值

{context_info}
方法名: {method_name}
方法代码:
```python
{method_code}
```

描述:"""
```

#### 支持多语言描述

```python
def _build_prompt(self, ..., lang: str = 'zh') -> str:
    if lang == 'en':
        prompt = f"""Analyze the following Python method..."""
    elif lang == 'zh':
        prompt = f"""请分析以下Python方法..."""
    # ...
```

---

### 3. 支持其他节点类型

#### 扩展描述生成器

创建通用的描述生成接口：

```python
def generate_node_description(self, node_type: str, node_code: str, 
                              node_name: str, relations: dict = None) -> str:
    """
    通用的节点描述生成器
    
    Args:
        node_type: 节点类型 (METHOD, CLASS, FUNCTION等)
        node_code: 节点代码
        node_name: 节点名称
        relations: 关系信息
    """
    if node_type == 'METHOD':
        return self.generate_method_description(...)
    elif node_type == 'CLASS':
        return self._generate_class_description(...)
    elif node_type == 'FUNCTION':
        return self.generate_method_description(...)  # 复用METHOD逻辑
    # ...
```

#### 在 my_client.py 中集成

```python
def _generate_node_description(self, full_name: str, kind: str, data: dict) -> str:
    """为任意类型节点生成描述"""
    description_generator = get_description_generator()
    
    if kind in ['METHOD', 'FUNCTION']:
        relations = self.graphDB.get_node_relations(full_name)
        return description_generator.generate_node_description(
            node_type=kind,
            node_code=data.get('code', ''),
            node_name=data.get('name', ''),
            relations=relations
        )
    elif kind == 'CLASS':
        # 类节点的特殊处理
        # ...
```

---

### 4. 优化性能

#### 批量查询关系

如果一次需要为多个节点生成描述，可以批量查询关系：

```python
def get_nodes_relations(self, full_names: list) -> dict:
    """批量获取多个节点的关系"""
    # 使用单个Cypher查询获取所有关系
    cypher = """
        MATCH (src)-[r:CALL]->(dst)
        WHERE dst.full_name IN $full_names
        RETURN dst.full_name AS node, src.full_name AS caller
    """
    rs = self.execute_query(cypher, full_names=full_names)
    
    # 聚合结果
    relations_dict = {name: {'incoming_calls': []} for name in full_names}
    for r in rs:
        relations_dict[r['node']]['incoming_calls'].append(r['caller'])
    
    return relations_dict
```

#### 关系缓存

```python
class MethodDescriptionGenerator:
    def __init__(self, ...):
        self.relations_cache = {}  # 缓存关系信息
    
    def get_cached_relations(self, full_name: str, graph_db):
        """获取缓存的关系信息"""
        if full_name not in self.relations_cache:
            self.relations_cache[full_name] = graph_db.get_node_relations(full_name)
        return self.relations_cache[full_name]
```

---

### 5. 自定义关系分析深度

#### 支持多跳关系

```python
def get_node_relations(self, full_name, depth: int = 1):
    """
    获取节点的关系，支持多跳查询
    
    Args:
        full_name: 节点名称
        depth: 关系深度（1=直接关系，2=二级关系等）
    """
    if depth == 1:
        # 现有逻辑
        return self._get_direct_relations(full_name)
    elif depth == 2:
        # 二级关系
        cypher = """
            MATCH (src)-[r1:CALL]->(middle)-[r2:CALL]->(dst {full_name: $full_name})
            RETURN src.full_name AS caller, middle.full_name AS intermediate
        """
        # ...
```

---

### 6. 关系权重和重要性排序

```python
def get_node_relations(self, full_name):
    relations = {
        'incoming_calls': [],
        'outgoing_calls': [],
        # ...
    }
    
    # 查询关系并添加权重
    cypher = """
        MATCH (src)-[r:CALL]->(dst {full_name: $full_name})
        RETURN src.full_name AS caller, count(r) AS call_count
        ORDER BY call_count DESC
        LIMIT 10
    """
    # 只返回调用频率最高的10个
```

---

## 测试和验证

### 验证关系查询

```python
# 测试 get_node_relations
relations = graph_db.get_node_relations("module.ClassName.method_name")
print(relations)
# 预期输出:
# {
#     'incoming_calls': ['module.other_func', 'module.another_func'],
#     'outgoing_calls': ['math.log', 'utils.helper'],
#     'inherits_from': ['BaseClass'],
#     'inherited_by': []
# }
```

### 验证描述生成

```python
from method_description_generator import get_description_generator

generator = get_description_generator()
description = generator.generate_method_description(
    method_code="def calculate(x, y): return x + y",
    method_name="calculate",
    relations={
        'incoming_calls': ['main', 'processor'],
        'outgoing_calls': ['math.sqrt']
    }
)
print(description)
# 预期输出包含关系信息
```

---

## 常见问题

### Q1: 关系查询性能慢怎么办？
**A**: 考虑：
- 在Neo4j中为 `full_name` 创建索引
- 使用批量查询而不是逐个查询
- 限制关系数量（如只查询最重要的前N个）

### Q2: 如何过滤不重要关系？
**A**: 在 `get_node_relations` 中添加过滤逻辑：
```python
# 只返回调用次数超过阈值的调用者
if call_count >= threshold:
    relations['incoming_calls'].append(caller)
```

### Q3: 描述太长怎么办？
**A**: 
- 在 `_build_prompt` 中进一步限制关系列表长度
- 只显示最重要的关系（如调用频率最高的）
- 调整LLM的 `max_tokens` 参数

---

## 总结

通过以上修改，我们实现了：
1. ✅ 从图数据库查询节点关系的能力
2. ✅ 将关系信息传递给描述生成器
3. ✅ 在LLM提示词中融合关系信息
4. ✅ 生成包含结构上下文的智能描述

**核心改进**: 描述生成不再孤立分析单个方法，而是结合其在代码图谱中的位置和关系，提供更全面的理解。

---

## 相关文件

- `method_description_generator.py`: 核心描述生成逻辑
- `my_client.py`: 客户端集成代码
- `my_graph_db.py`: 图数据库操作和关系查询
- `README_METHOD_DESCRIPTION.md`: 本文件

---

## 更新日志

- **2024-XX-XX**: 初始实现，支持基本的方法描述生成
- **2024-XX-XX**: 添加结构关系分析功能，融合调用和继承关系到描述中
