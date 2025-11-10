# c_code_analyzer/ast_visitor_client.py
from mock_dependencies import (
    MockGraphDB, MockSymbolRegistry, MockSymbolReferenceRegistry,
    srctrl, symbolKindToString, referenceKindToString, 
    NameHierarchy, SourceRange
)
import os 

class AstVisitorClient:

    def __init__(self, graphDB: MockGraphDB, task_root_path=''):
        self.indexedFileId = 0
        self.symbol = MockSymbolRegistry()
        self.symbol_rela = MockSymbolReferenceRegistry()
        self.task_root_path = self._normalize_path(task_root_path) 
        self.graphDB = graphDB
        
        self.this_file_path = ''
        self.this_source_code_lines = []
        
        self.symbol_data = {}
        self.symbol_data['builtins'] = {
            'name': 'builtins',
            'kind': 'MODULE',
            'parent_name': '',
        }
        self.symbolId_to_Name = {}
        self.indexedFileId_to_path = {}
        self.referenceId_to_data = {}
        self.referenceId_to_data['Unsolved'] = []
        
        self.global_symbol_definitions = {} 
        self.global_symbol_ids = {}

        self.scope_stack = ['code_repository_root'] 
        self.scope_id_stack = [self.symbol.record_symbol('code_repository_root')]
        
        self.graphDB.add_node(label='REPOSITORY', full_name='code_repository_root', parms={'path': self.task_root_path})


    def _normalize_path(self, path):
        """规范化路径，确保以目录分隔符结尾（如果不是空路径）"""
        if not path:
            return ''
        return os.path.normpath(path) + os.sep


    def process_new_file(self, file_path, source_code_bytes):
        """
        处理一个新的文件，更新客户端的上下文。
        应该在每次开始分析一个新文件时调用。
        """
        self.this_file_path = self._normalize_path(file_path)
        self.this_source_code_lines = source_code_bytes.decode('utf8', errors='ignore').split('\n')
        
        relative_file_path = self.process_file_path(self.this_file_path)
        
        file_name = relative_file_path 
        file_id = self.symbol.record_symbol(file_name)
        self.symbolId_to_Name[file_id] = file_name
        
        if file_name not in self.symbol_data:
            self.symbol_data[file_name] = {
                'name': file_name,
                'path': relative_file_path,
                'file_path': relative_file_path,
                'kind': 'FILE', 
                'parent_name': 'code_repository_root', 
                'full_name': file_name,
            }
            # 统一使用 file_path 属性，增加 name/full_name/type 等字段，便于查询
            self.graphDB.add_node(label='FILE', full_name=file_name, 
                                  parms={
                                      'file_path': relative_file_path,
                                      'absolute_path': self.this_file_path,
                                      'name': file_name,
                                      'full_name': file_name,
                                      'type': 'FILE'
                                  })
            
            self.graphDB.add_edge(
                start_label='REPOSITORY',
                start_name='code_repository_root',
                relationship_type='CONTAINS_FILE',
                end_label='FILE',
                end_name=file_name,
                params={'association_type': 'FILE'}
            )

        self.scope_stack = ['code_repository_root', file_name]
        self.scope_id_stack = [self.symbol.record_symbol('code_repository_root'), file_id]
        
        #print(f"  [CLIENT] Processing new file module: {file_name}")
        return file_name, file_id


    def process_file_path(self, file_path):
        """将绝对文件路径转换为相对于 task_root_path 的路径"""
        if self.task_root_path and file_path.startswith(self.task_root_path):
            return os.path.relpath(file_path, self.task_root_path).replace(os.sep, '/')
        return file_path.replace(os.sep, '/')
    
    def normalize_header_path(self, header_path):
        """
        标准化 header 文件路径。
        尝试在 task_root_path 中查找实际的 header 文件，
        如果找到，返回相对于 task_root_path 的标准路径。
        否则返回原始路径（可能是系统 header）。
        """
        # 移除引号和尖括号
        header_path = header_path.strip('<>"\'')
        
        # 如果是绝对路径，直接处理
        if os.path.isabs(header_path):
            return self.process_file_path(header_path)
        
        # 尝试在项目根目录中查找此 header 文件
        if self.task_root_path:
            # 尝试直接路径
            full_path = os.path.join(self.task_root_path, header_path)
            if os.path.exists(full_path):
                return header_path.replace(os.sep, '/')
            
            # 尝试搜索整个项目目录
            for root, dirs, files in os.walk(self.task_root_path):
                header_basename = os.path.basename(header_path)
                if header_basename in files:
                    # 找到了文件，返回相对路径
                    found_path = os.path.join(root, header_basename)
                    return self.process_file_path(found_path)
        
        # 如果找不到，返回原始路径（可能是系统 header）
        return header_path.replace(os.sep, '/') 

    def extract_code_between_lines(self, start_line, end_line, is_indent=True, is_code=True):
        """
        模拟从内存中的源代码行提取代码片段。
        start_line 和 end_line 是基于 1 的行号。
        """
        if not self.this_source_code_lines:
            return "// No source code loaded for extraction"
            
        start_idx = max(0, start_line - 1)
        end_idx = min(len(self.this_source_code_lines), end_line)
        
        lines = self.this_source_code_lines[start_idx:end_idx]
        
        if is_code:
            return "\n".join(lines)
        return f'// Code from line {start_line} to {end_line}'

    def recordSymbol(self, nameHierarchy: NameHierarchy, node_path='', tree_node=None, global_node=None, kind_hint=None):
        """
        记录符号的基本信息和层次结构。
        增加了 kind_hint 参数，用于在创建时给一个初步的类型提示。
        """
        name_short = nameHierarchy.getDisplayString().split('.')[-1]
        parent_name = nameHierarchy.getParentDisplayString()
        
        # 确定符号的完整名称
        full_name = None
        if name_short in self.global_symbol_definitions:
            full_name = self.global_symbol_definitions[name_short]
        else:
            if self.scope_stack[1] != 'code_repository_root': 
                file_name = self.scope_stack[1]
                full_name = f"{file_name}.{name_short}"
            else:
                full_name = name_short 
        
        if full_name is None:
            full_name = name_short

        symbolId = self.symbol.record_symbol(full_name)
        self.symbolId_to_Name[symbolId] = full_name

        if full_name not in self.symbol_data:
            self.symbol_data[full_name] = {
                'name': name_short,
                'path': self.process_file_path(node_path),
                'file_path': self.process_file_path(node_path),
                'kind': kind_hint if kind_hint else '', 
                'parent_name': parent_name,
                'full_name': full_name,
                'references': [] 
            }
        else:
            pass
        
        if 'references' not in self.symbol_data[full_name]:
            self.symbol_data[full_name]['references'] = []
        
        # 更新符号的类型，如果新的 kind_hint 更精确
        current_kind = self.symbol_data[full_name].get('kind')
        
        # 定义一个类型优先级函数，数值越高表示越精确
        def get_kind_priority(kind_str):
            priority_map = {
                symbolKindToString(srctrl.SymbolKind.UNKNOWN): 0, # <--- 修改
                symbolKindToString(srctrl.SymbolKind.EXTERNAL_VARIABLE): 1, # <--- 修改
                symbolKindToString(srctrl.SymbolKind.FUNCTION_DECLARATION): 1, # <--- 修改
                symbolKindToString(srctrl.SymbolKind.GLOBAL_VARIABLE): 2, # <--- 修改
                symbolKindToString(srctrl.SymbolKind.GLOBAL_CONSTANT): 2, # <--- 修改
                symbolKindToString(srctrl.SymbolKind.STATIC_VARIABLE): 2, # <--- 新增
                symbolKindToString(srctrl.SymbolKind.STRUCT_MEMBER): 2, # <--- 新增
                symbolKindToString(srctrl.SymbolKind.FUNCTION): 3, # <--- 修改
                symbolKindToString(srctrl.SymbolKind.STRUCT): 3, # <--- 修改
                symbolKindToString(srctrl.SymbolKind.UNION): 3, # <--- 修改
                symbolKindToString(srctrl.SymbolKind.ENUM): 3, # <--- 修改
                symbolKindToString(srctrl.SymbolKind.TYPEDEF): 3, # <--- 修改
                symbolKindToString(srctrl.SymbolKind.MACRO): 3, # <--- 修改
            }
            return priority_map.get(kind_str, 0)


        # 只有当新的 kind_hint 更精确时才更新
        if kind_hint and get_kind_priority(kind_hint) > get_kind_priority(current_kind):
            self.symbol_data[full_name]['kind'] = kind_hint
        
        # 如果这是一个定义或明确的声明，将其短名加入全局定义映射
        # 现在包括所有新定义的类型
        if kind_hint in [
            'FUNCTION', 'GLOBAL_VARIABLE', 'FUNCTION_DECLARATION',
            'STRUCT', 'UNION', 'ENUM', 'TYPEDEF', 'MACRO', 'GLOBAL_CONSTANT',
             'STATIC_VARIABLE', 'STRUCT_MEMBER'
        ]:
            current_global_def_full_name = self.global_symbol_definitions.get(name_short)
            
            # 只有当全局定义不存在，或者当前注册的类型优先级低于新的类型优先级时才更新
            if current_global_def_full_name is None or \
               get_kind_priority(kind_hint) > get_kind_priority(self.symbol_data.get(current_global_def_full_name, {}).get('kind', 'UNKNOWN')):
                self.global_symbol_definitions[name_short] = full_name
                self.global_symbol_ids[name_short] = symbolId
        
        return symbolId

    def recordSymbolKind(self, symbolId, symbolKind, attributes=None):
        """记录符号类型，并在数据库中创建节点和关系"""
        full_name = self.symbolId_to_Name[symbolId]
        kind = symbolKindToString(symbolKind)
        
        current_kind = self.symbol_data[full_name].get('kind')
        
        # 定义类型优先级函数，与 recordSymbol 中保持一致
        def get_kind_priority(kind_str):
            priority_map = {
                symbolKindToString(srctrl.SymbolKind.UNKNOWN): 0,
                symbolKindToString(srctrl.SymbolKind.EXTERNAL_VARIABLE): 1,
                symbolKindToString(srctrl.SymbolKind.FUNCTION_DECLARATION): 1,
                symbolKindToString(srctrl.SymbolKind.GLOBAL_VARIABLE): 2,
                symbolKindToString(srctrl.SymbolKind.GLOBAL_CONSTANT): 2,
                symbolKindToString(srctrl.SymbolKind.STATIC_VARIABLE): 2,
                symbolKindToString(srctrl.SymbolKind.STRUCT_MEMBER): 2,
                symbolKindToString(srctrl.SymbolKind.FUNCTION): 3,
                symbolKindToString(srctrl.SymbolKind.STRUCT): 3,
                symbolKindToString(srctrl.SymbolKind.UNION): 3,
                symbolKindToString(srctrl.SymbolKind.ENUM): 3,
                symbolKindToString(srctrl.SymbolKind.TYPEDEF): 3,
                symbolKindToString(srctrl.SymbolKind.MACRO): 3
            }
            return priority_map.get(kind_str, 0)
            
        # 只有当新的 kind 更精确时才更新 symbol_data
        if get_kind_priority(kind) > get_kind_priority(current_kind):
            self.symbol_data[full_name]['kind'] = kind
        
        data = {
            'name': self.symbol_data[full_name].get('name'), 
            'file_path': self.symbol_data[full_name].get('path', ''), 
            'full_name': full_name
        }
        
        # 如果是函数且有额外属性，添加到data中
        if kind == 'FUNCTION' and attributes:
            if 'signature' in attributes:
                data['signature'] = attributes['signature']
            # 兼容性：把 parameters/return_type 等也写入为字符串，方便后续查询和展示
            if 'parameters' in attributes:
                try:
                    data['parameters'] = str(attributes['parameters'])
                except Exception:
                    data['parameters'] = attributes['parameters']
            if 'return_type' in attributes:
                data['return_type'] = attributes['return_type']
        
        # 1. 创建节点（或更新其标签）
        self.graphDB.add_node(label=kind, full_name=full_name, parms=data)
        
        # 2. 创建关系：CONTAINS (模块包含)
        # 扩展此列表以包含所有新类型
        if kind in [
            'FUNCTION', 'GLOBAL_VARIABLE', 'FUNCTION_DECLARATION',
            'STRUCT', 'UNION', 'ENUM', 'TYPEDEF', 'MACRO', 'GLOBAL_CONSTANT',
             'STATIC_VARIABLE', 'STRUCT_MEMBER'
        ]:
            file_name = self.scope_stack[1] 
            # Ensure the symbol node has file_path/name/type properties when created
            # add_node will merge properties if node already exists
            node_parms = {
                # Ensure a short display name is available; fall back to last segment of full_name
                'name': self.symbol_data[full_name].get('name', full_name.split('.')[-1]),
                'file_path': self.symbol_data[full_name].get('path', ''),
                'full_name': full_name,
                'type': kind,
            }
            # If signature/code exists in symbol_data, include them
            if 'signature' in self.symbol_data[full_name]:
                node_parms['signature'] = self.symbol_data[full_name]['signature']
            if 'code' in self.symbol_data[full_name]:
                node_parms['code'] = self.symbol_data[full_name]['code']

            self.graphDB.add_node(label=kind, full_name=full_name, parms=node_parms)

            self.graphDB.add_edge(
                start_label='FILE',
                start_name=file_name,
                relationship_type='CONTAINS',
                end_label=kind,
                end_name=full_name,
                params={'association_type': kind},
            )

    def recordSymbolScopeLocation(self, symbolId, sourceRange: SourceRange):
        """记录符号的整个作用域（代码块）"""
        name = self.symbolId_to_Name.get(symbolId, 'Unknown')
        kind = self.symbol_data.get(name, {}).get('kind', 'UNKNOWN')

        # 扩展此列表以包含结构体、联合体、枚举等定义，它们也有代码块
        if kind in ['FUNCTION', 'STRUCT', 'UNION', 'ENUM']: # 枚举体本身也可以有定义体
            code = self.extract_code_between_lines(
                sourceRange.startLine, sourceRange.endLine, is_indent=True, is_code=True)

            # Update node with code and ensure file_path is present on scope nodes
            node_parms = {
                'code': code,
                'file_path': self.symbol_data.get(name, {}).get('path', ''),
            }
            self.graphDB.add_node(kind, full_name=name, parms=node_parms)
            #print(f"  [CLIENT] Recorded Scope for {kind}: {name}")

    def resolve_referenced_symbol(self, callee_name_short: str):
        """
        尝试解析被引用符号的完整名称和ID。
        优先从全局定义中查找，否则创建文件模块限定的名称。
        """
        if callee_name_short in self.global_symbol_definitions:
            full_name = self.global_symbol_definitions[callee_name_short]
            symbol_id = self.global_symbol_ids[callee_name_short]
            return full_name, symbol_id
        else:
            # 如果是第一次遇到，或者是一个外部未定义的符号，创建一个文件模块限定的符号名作为占位符
            # 这仍然可能需要后续的链接阶段来解决
            file_name = self.scope_stack[1]
            full_name = f"{file_name}.{callee_name_short}"
            symbol_id = self.symbol.record_symbol(full_name)
            self.symbolId_to_Name[symbol_id] = full_name
            # 如果不存在，先记录一个UNKNOWN类型的占位符
            if full_name not in self.symbol_data:
                self.symbol_data[full_name] = {
                    'name': callee_name_short,
                    'path': self.process_file_path(self.this_file_path),
                    'kind': 'UNKNOWN',
                    'parent_name': file_name,
                    'full_name': full_name,
                    'references': [] # 记录指向此符号的引用
                }
            return full_name, symbol_id

    def recordReference(self, contextSymbolId, referencedSymbolId, referenceKind):
        """记录引用关系，并在数据库中创建边"""
        referenceKindStr = referenceKindToString(referenceKind)
        
        referenceName = self.symbolId_to_Name.get(referencedSymbolId, 'UnknownRef')
        contextName = self.symbolId_to_Name.get(contextSymbolId, 'UnknownContext')

        contextKind = self.symbol_data.get(contextName, {}).get('kind', 'UNKNOWN')
        referencedKind = self.symbol_data.get(referenceName, {}).get('kind', 'UNKNOWN')

        edge_id = None
        if referenceKindStr == 'CALL':
            if contextKind == 'FUNCTION':
                # 确保被引用的节点存在（即使类型是UNKNOWN）
                if not self.graphDB.get_node(referenceName):
                    ref_data = self.symbol_data.get(referenceName, {})
                    self.graphDB.add_node(
                        label=referencedKind,
                        full_name=referenceName,
                        parms={
                            'name': ref_data.get('name', referenceName),
                            'file_path': ref_data.get('path', ''),
                            'full_name': referenceName
                        }
                    )
                
                edge_id = self.graphDB.add_edge(
                    start_label=contextKind,
                    start_name=contextName,
                    relationship_type='CALL',
                    end_label=referencedKind, 
                    end_name=referenceName,
                )
        elif referenceKindStr == 'INCLUDE':
            current_file_name = self.scope_stack[1] 
            # INCLUDE 的 start_label 是 FILE，end_label 是 HEADER
            edge_id = self.graphDB.add_edge(
                start_label='FILE',
                start_name=current_file_name,
                relationship_type='INCLUDE',
                end_label='HEADER', 
                end_name=referenceName, 
            )
        elif referenceKindStr == 'USAGE': 
            if contextKind in ['FUNCTION', 'GLOBAL_VARIABLE', 'FILE',
                               symbolKindToString(srctrl.SymbolKind.STRUCT), 
                               symbolKindToString(srctrl.SymbolKind.UNION),
                               symbolKindToString(srctrl.SymbolKind.ENUM),
                               symbolKindToString(srctrl.SymbolKind.TYPEDEF),
                               symbolKindToString(srctrl.SymbolKind.MACRO),
                               symbolKindToString(srctrl.SymbolKind.GLOBAL_CONSTANT),
                               ]:
                # 确保被引用的节点存在
                if not self.graphDB.get_node(referenceName):
                    ref_data = self.symbol_data.get(referenceName, {})
                    self.graphDB.add_node(
                        label=referencedKind,
                        full_name=referenceName,
                        parms={
                            'name': ref_data.get('name', referenceName),
                            'file_path': ref_data.get('path', ''),
                            'full_name': referenceName
                        }
                    )
                
                edge_id = self.graphDB.add_edge(
                    start_label=contextKind,
                    start_name=contextName,
                    relationship_type='USES', 
                    end_label=referencedKind, 
                    end_name=referenceName,
                )
                 
        # 确保 contextName 存在于 symbol_data 并且有 'references' 键
        if contextName in self.symbol_data:
            if 'references' not in self.symbol_data[contextName]:
                self.symbol_data[contextName]['references'] = []
            
            if edge_id is not None:
                self.symbol_data[contextName]['references'].append(
                    {'edge_id': edge_id, 'referenced_full_name': referenceName, 'referenceKind': referenceKindStr}
                )

        recorded_ref_id = self.symbol_rela.record_reference(
            contextSymbolId, referencedSymbolId, referenceKind)
        return recorded_ref_id
    # 作用域管理方法
    def push_scope(self, symbol_name, symbol_id):
        self.scope_stack.append(symbol_name)
        self.scope_id_stack.append(symbol_id)

    def pop_scope(self):
        # 确保不会弹出代码库根和文件模块这两个基础作用域
        if len(self.scope_stack) > 2: # 'code_repository_root', 'file_name'
            self.scope_stack.pop()
            self.scope_id_stack.pop()
        
    def current_context_name(self):
        return self.scope_stack[-1]
    
    def current_context_id(self):
        return self.scope_id_stack[-1]

    # === 新增：后处理引用关系的方法 ===
    def post_process_references(self):
        """
        后处理阶段：解析所有UNKNOWN符号到实际定义，建立跨文件引用关系
        """
        print("\n--- 开始后处理引用关系 ---")
        symbols_to_delete = set()
        edges_to_update = []  # 收集需要更新的边

        # 第一步：遍历所有符号，查找发出的引用
        for full_name_of_context, data_of_context in self.symbol_data.items():
            if 'references' not in data_of_context:
                continue
                
            for ref_info in data_of_context['references']:
                edge_id = ref_info.get('edge_id')
                if edge_id is None:
                    continue
                    
                referenced_full_name_temp = ref_info['referenced_full_name']
                referenced_short_name = referenced_full_name_temp.split('.')[-1]
                reference_kind_str = ref_info.get('referenceKind', 'USAGE')
                
                # 尝试从全局定义中解析
                resolved_full_name = self.global_symbol_definitions.get(referenced_short_name)
                
                if not resolved_full_name:
                    continue
                
                # 获取解析后的符号类型
                resolved_kind = self.symbol_data.get(resolved_full_name, {}).get('kind', 'UNKNOWN')
                
                # 获取当前边的信息
                current_node = self.graphDB.get_node(referenced_full_name_temp)
                current_edge_end_node_label = current_node['label'] if current_node else 'UNKNOWN'
                
                # 判断是否需要更新
                should_update = False
                
                # 场景1: 指向临时UNKNOWN节点，且找到了真实定义
                if (current_edge_end_node_label == 'UNKNOWN' and 
                    referenced_full_name_temp != resolved_full_name):
                    should_update = True
                    #print(f"  [POST] Resolving {referenced_full_name_temp} -> {resolved_full_name} ({resolved_kind})")
                
                # 场景2: 指向文件限定的符号，但找到了更明确的定义
                elif ('.' in referenced_full_name_temp and 
                      referenced_full_name_temp != resolved_full_name and
                      resolved_kind not in ['UNKNOWN', 'FUNCTION_DECLARATION']):
                    should_update = True
                    #print(f"  [POST] Refining {referenced_full_name_temp} -> {resolved_full_name} ({resolved_kind})")
                
                if should_update:
                    edges_to_update.append({
                        'edge_id': edge_id,
                        'new_end_name': resolved_full_name,
                        'new_end_label': resolved_kind,
                        'old_end_name': referenced_full_name_temp,
                        'reference_kind': reference_kind_str,
                        'context_full_name': full_name_of_context,
                    })
        
        # 第二步：批量更新边
        edge_type_map = {
            'CALL': 'CALL',
            'USAGE': 'USES',
            'USES': 'USES',
            'INCLUDE': 'INCLUDE',
        }
        for update_info in edges_to_update:
            edge_type = edge_type_map.get(update_info.get('reference_kind', 'USAGE'), 'USES')
            self.graphDB.update_edge(
                edge_id=update_info['edge_id'],
                source_id=update_info['context_full_name'],
                edge_type=edge_type,
                target_id=update_info['old_end_name'],
                new_target_id=update_info['new_end_name'],
            )
            symbols_to_delete.add(update_info['old_end_name'])
        
        # 第三步：清理不再需要的UNKNOWN节点
        actually_deleted = []
        for symbol_name in symbols_to_delete:
            # 检查节点是否存在且为UNKNOWN类型
            node = self.graphDB.get_node(symbol_name)
            if not node or node['label'] != 'UNKNOWN':
                continue
            
            # 检查是否还有其他边指向此节点
            has_remaining_references = any(
                edge['end_name'] == symbol_name 
                for edge in self.graphDB.edges
            )
            
            if not has_remaining_references:
                self.graphDB.delete_node(symbol_name)
                
                # 从 symbol_data 中移除
                if symbol_name in self.symbol_data:
                    del self.symbol_data[symbol_name]
                
                # 从 symbolId_to_Name 中移除
                ids_to_remove = [k for k, v in self.symbolId_to_Name.items() if v == symbol_name]
                for id_to_remove in ids_to_remove:
                    del self.symbolId_to_Name[id_to_remove]
                
                actually_deleted.append(symbol_name)
        
        # 第四步：清理所有孤立的UNKNOWN节点（没有任何边指向它们的节点）
        orphaned_unknowns = []
        for full_name, node in self.graphDB.nodes.items():
            if node['label'] == 'UNKNOWN':
                # 检查是否有任何边以此节点作为终点
                has_incoming_edges = any(
                    edge['end_name'] == full_name 
                    for edge in self.graphDB.edges
                )
                # 检查是否有任何边以此节点作为起点
                has_outgoing_edges = any(
                    edge['start_name'] == full_name
                    for edge in self.graphDB.edges
                )
                
                # 如果没有任何边连接到此节点，标记为孤立节点
                if not has_incoming_edges and not has_outgoing_edges:
                    orphaned_unknowns.append(full_name)
        
        for symbol_name in orphaned_unknowns:
            self.graphDB.delete_node(symbol_name)
            
            # 从 symbol_data 中移除
            if symbol_name in self.symbol_data:
                del self.symbol_data[symbol_name]
            
            # 从 symbolId_to_Name 中移除
            ids_to_remove = [k for k, v in self.symbolId_to_Name.items() if v == symbol_name]
            for id_to_remove in ids_to_remove:
                del self.symbolId_to_Name[id_to_remove]
            
            actually_deleted.append(symbol_name)
        
        # 第五步：清理 symbol_data 中存在但 graphDB.nodes 中不存在的 UNKNOWN 符号
        # 这些是在 resolve_referenced_symbol 中创建但从未添加到图数据库的符号
        orphaned_in_symbol_data = []
        for symbol_name, symbol_info in list(self.symbol_data.items()):
            if symbol_info.get('kind') == 'UNKNOWN':
                if symbol_name not in self.graphDB.nodes:
                    orphaned_in_symbol_data.append(symbol_name)
        
        for symbol_name in orphaned_in_symbol_data:
            # 从 symbol_data 中移除
            if symbol_name in self.symbol_data:
                del self.symbol_data[symbol_name]
            
            # 从 symbolId_to_Name 中移除
            ids_to_remove = [k for k, v in self.symbolId_to_Name.items() if v == symbol_name]
            for id_to_remove in ids_to_remove:
                del self.symbolId_to_Name[id_to_remove]
            
            actually_deleted.append(symbol_name)
        
        #if actually_deleted:
            #print(f"  [POST] Deleted {len(actually_deleted)} resolved/orphaned UNKNOWN nodes")
        
        #print("--- 后处理引用关系完成 ---")