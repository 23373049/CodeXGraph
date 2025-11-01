# c_code_analyzer/mock_dependencies.py

"""
模拟外部依赖的模块。
包括模拟图数据库、符号注册、引用注册，以及一些常量和辅助函数。
"""

class MockGraphDB:
    def __init__(self):
        self.nodes = {}
        self.edges = []
        self.next_node_id = 0
        self.next_edge_id = 0

    def add_node(self, label, full_name, parms=None):
        parms = parms if parms is not None else {}
        node_id = self.nodes.get(full_name, {}).get('id')
        
        if node_id is None:
            node_id = self.next_node_id
            self.next_node_id += 1
            self.nodes[full_name] = {'id': node_id, 'label': label, 'full_name': full_name, 'parms': parms.copy()}
            print(f"  [DB_NODE] ADD: {label:<10} | {full_name} | {parms}")
        else:
            # 如果节点已存在，更新其参数
            existing_node_parms = self.nodes[full_name]['parms']
            updated_parms = False
            for key, value in parms.items():
                if existing_node_parms.get(key) != value:
                    existing_node_parms[key] = value
                    updated_parms = True
            
            # 特殊处理，如果类型从 DECLARATION 升级到 FUNCTION，也更新 label
            if self.nodes[full_name]['label'] == 'FUNCTION_DECLARATION' and label == 'FUNCTION':
                self.nodes[full_name]['label'] = label
                updated_parms = True

            if updated_parms:
                print(f"  [DB_NODE] UPDATE: {self.nodes[full_name]['label']:<10} | {full_name} | {existing_node_parms}")
            # print(f"  [DB_NODE] EXISTS: {label:<10} | {full_name}") # 可以取消注释查看更多日志
        
        return node_id

    def add_edge(self, start_label, start_name, relationship_type, end_label, end_name, params=None):
        start_node_info = self.nodes.get(start_name)
        end_node_info = self.nodes.get(end_name)

        if not start_node_info or not end_node_info:
            # 可以在这里处理未找到节点的错误，或者选择不添加边
            # print(f"  [DB_EDGE_ERROR] Node not found for edge: {start_name} -> {end_name}")
            return None # 或者引发异常

        start_id = start_node_info['id']
        end_id = end_node_info['id']
        
        # 检查是否已存在完全相同的边，避免重复
        for edge in self.edges:
            if (edge['start_id'] == start_id and 
                edge['relationship_type'] == relationship_type and 
                edge['end_id'] == end_id):
                return edge['id'] # 边已存在，返回其ID
        
        edge_id = self.next_edge_id
        self.next_edge_id += 1
        edge = {
            'id': edge_id,
            'start_id': start_id,
            'start_name': start_name,
            'start_label': start_label,
            'relationship_type': relationship_type,
            'end_id': end_id,
            'end_name': end_name,
            'end_label': end_label,
            'params': params if params is not None else {}
        }
        self.edges.append(edge)
        print(f"  [DB_EDGE] EDGE: {start_name} -> {relationship_type} -> {end_name} (Type: {end_label})")
        return edge_id

    def get_node(self, full_name):
        return self.nodes.get(full_name)

    def get_node_by_id(self, node_id):
        for full_name, node_data in self.nodes.items():
            if node_data['id'] == node_id:
                return node_data
        return None

    # === 新增：更新边的方法 ===
    def update_edge(self, edge_id, new_end_name=None, new_end_label=None):
        for edge in self.edges:
            if edge['id'] == edge_id:
                old_end_name = edge['end_name']
                old_end_label = edge['end_label']
                
                updated = False
                if new_end_name and new_end_name != old_end_name:
                    new_end_node = self.nodes.get(new_end_name)
                    if new_end_node:
                        edge['end_name'] = new_end_name
                        edge['end_id'] = new_end_node['id']
                        updated = True
                    else:
                        print(f"  [DB_UPDATE_EDGE_ERROR] New end node '{new_end_name}' not found for edge {edge_id}")
                        return False
                
                if new_end_label and new_end_label != old_end_label:
                    edge['end_label'] = new_end_label
                    updated = True
                
                if updated:
                    print(f"  [DB_EDGE_UPDATED] Edge {edge_id}: {edge['start_name']} -> {edge['relationship_type']} -> {edge['end_name']} (Type: {edge['end_label']})")
                return updated
        print(f"  [DB_UPDATE_EDGE_ERROR] Edge with ID {edge_id} not found.")
        return False
    
    # === 新增：删除节点的方法 ===
    def delete_node(self, full_name):
        if full_name in self.nodes:
            node_id_to_delete = self.nodes[full_name]['id']
            del self.nodes[full_name]
            
            # 同时删除所有与该节点相关的边
            self.edges = [edge for edge in self.edges if edge['start_id'] != node_id_to_delete and edge['end_id'] != node_id_to_delete]
            
            print(f"  [DB_NODE_DELETED] Node '{full_name}' and its associated edges deleted.")
            return True
        print(f"  [DB_NODE_DELETE_ERROR] Node '{full_name}' not found.")
        return False
    
class MockSymbolRegistry:
    """模拟符号注册，简单地返回基于名称的哈希ID"""
    def record_symbol(self, name):
        # 使用哈希值作为唯一的 SymbolId
        return hash(name) % 10000 

class MockSymbolReferenceRegistry:
    """模拟引用注册"""
    def record_reference(self, *args):
        return 1

class SymbolKind: 
    UNKNOWN = 0
    MODULE = 1
    FILE = 2
    FUNCTION = 3
    GLOBAL_VARIABLE = 4
    FUNCTION_DECLARATION = 5
    STRUCT = 6
    UNION = 7
    ENUM = 8
    TYPEDEF = 9
    MACRO = 10
    GLOBAL_CONSTANT = 11 
    # 新增的符号类型
    STRUCT_MEMBER = 12
    STATIC_VARIABLE = 14
    EXTERNAL_VARIABLE = 15 
    FUNCTION_PARAMETER = 16
    FUNCTION_POINTER = 17


class ReferenceKind: 
    UNKNOWN = 0 
    CALL = 1
    INCLUDE = 2
    USAGE = 3
    DEFINITION = 4
    # 新增的关系类型
    HAS_MEMBER = 5
    HAS_PARAMETER = 6 


# === SRCTools 类来封装 SymbolKind 和 ReferenceKind 类 ===
# 这个类将作为全局的 srctrl 实例的类型
class SRCTools:
    def __init__(self):
        # 将 SymbolKind 和 ReferenceKind 类本身作为实例的属性
        self.SymbolKind = SymbolKind
        self.ReferenceKind = ReferenceKind

# 实例化 SRCTools 类，并将其赋值给 srctrl 全局变量
srctrl = SRCTools()

# 类型到字符串的映射函数
# 这些函数现在将通过 srctrl.SymbolKind 或 srctrl.ReferenceKind 访问枚举值
def symbolKindToString(kind_value): # 改为 kind_value 以避免与类名冲突
    if kind_value == srctrl.SymbolKind.UNKNOWN: return "UNKNOWN"
    if kind_value == srctrl.SymbolKind.MODULE: return "MODULE"
    if kind_value == srctrl.SymbolKind.FILE: return "FILE"
    if kind_value == srctrl.SymbolKind.FUNCTION: return "FUNCTION"
    if kind_value == srctrl.SymbolKind.GLOBAL_VARIABLE: return "GLOBAL_VARIABLE"
    if kind_value == srctrl.SymbolKind.FUNCTION_DECLARATION: return "FUNCTION_DECLARATION"
    if kind_value == srctrl.SymbolKind.EXTERNAL_VARIABLE: return "EXTERNAL_VARIABLE"
    if kind_value == srctrl.SymbolKind.STRUCT: return "STRUCT"
    if kind_value == srctrl.SymbolKind.UNION: return "UNION"
    if kind_value == srctrl.SymbolKind.ENUM: return "ENUM"
    if kind_value == srctrl.SymbolKind.TYPEDEF: return "TYPEDEF"
    if kind_value == srctrl.SymbolKind.MACRO: return "MACRO"
    if kind_value == srctrl.SymbolKind.GLOBAL_CONSTANT: return "GLOBAL_CONSTANT"
    if kind_value == srctrl.SymbolKind.STRUCT_MEMBER: return "STRUCT_MEMBER"
    if kind_value == srctrl.SymbolKind.STATIC_VARIABLE: return "STATIC_VARIABLE"
    return "UNKNOWN"

def referenceKindToString(kind_value): # 改为 kind_value
    if kind_value == srctrl.ReferenceKind.UNKNOWN: return "UNKNOWN"
    if kind_value == srctrl.ReferenceKind.CALL: return "CALL"
    if kind_value == srctrl.ReferenceKind.INCLUDE: return "INCLUDE"
    if kind_value == srctrl.ReferenceKind.USAGE: return "USAGE"
    if kind_value == srctrl.ReferenceKind.DEFINITION: return "DEFINITION"
    # 新增的关系类型
    if kind_value == srctrl.ReferenceKind.HAS_MEMBER: return "HAS_MEMBER"
    if kind_value == srctrl.ReferenceKind.HAS_PARAMETER: return "HAS_PARAMETER"
    return "UNKNOWN"

# 辅助类：模拟 NameHierarchy
class NameHierarchy:
    def __init__(self, name, parent_name):
        self._name = name
        self._parent_name = parent_name
    def getDisplayString(self):
        return self._name
    def getParentDisplayString(self):
        return self._parent_name

class MockSymbolReferenceRegistry:
    def __init__(self):
        self._nextReferenceId = 0
        self._references = [] # 存储所有的引用数据

    def record_reference(self, context_symbol_id, referenced_symbol_id, reference_kind):
        reference_id = self._nextReferenceId
        self._nextReferenceId += 1
        
        # 将引用数据存储为字典，包含所有必要信息
        reference_data = {
            'id': reference_id,
            'context_symbol_id': context_symbol_id,
            'referenced_symbol_id': referenced_symbol_id,
            'reference_kind': reference_kind,
            # 可以添加其他信息，如源范围等
        }
        self._references.append(reference_data)
        print(f"  [SRCTR] Recorded Reference {reference_id}: {context_symbol_id} -> {referenceKindToString(reference_kind)} -> {referenced_symbol_id}")
        return reference_id

    # === 新增方法：用于获取所有引用 ===
    def get_all_references(self):
        return self._references
    
# 辅助类：模拟 SourceRange
class SourceRange:
    def __init__(self, startLine, endLine):
        self.startLine = startLine
        self.endLine = endLine