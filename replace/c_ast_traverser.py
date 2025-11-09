# c_code_analyzer/c_ast_traverser.py

from tree_sitter import Language, Parser, Node
import tree_sitter_c
import os 

from ast_visitor_client import AstVisitorClient
from function_category import FunctionCategory
from header_catalog import KNOWN_FUNCTIONS
# 从 mock_dependencies 中导入 srctrl 以及转换函数
from mock_dependencies import NameHierarchy, SourceRange, srctrl, symbolKindToString, referenceKindToString

def setup_c_parser():
    """
    设置 Tree-sitter 的 C 语言解析器。
    """
    try:
        # 新版本 tree-sitter (>= 0.22)
        C_LANGUAGE = Language(tree_sitter_c.language())
    except TypeError:
        # 旧版本 tree-sitter (< 0.22)
        C_LANGUAGE = Language(tree_sitter_c.language(), 'c')
    parser = Parser()
    try:
        parser.language = C_LANGUAGE
    except AttributeError:
        parser.set_language(C_LANGUAGE)
    return parser


def traverse_c_ast_and_record(client: AstVisitorClient, file_path: str):
    """
    解析 C 代码文件并使用 Tree-sitter 的 cursor 进行深度优先遍历，
    将提取的信息记录到 AstVisitorClient 中。
    """
    parser = setup_c_parser()

    print(f"\n--- 开始分析文件: {file_path} ---")

    try:
        with open(file_path, 'rb') as f: 
            c_code_bytes = f.read()
    except FileNotFoundError:
        print(f"  [ERROR] File not found: {file_path}")
        return
    except Exception as e:
        print(f"  [ERROR] Failed to read file {file_path}: {e}")
        return

    # 在处理新文件前，通知客户端更新其上下文
    file_name, file_id = client.process_new_file(file_path, c_code_bytes)

    tree = parser.parse(c_code_bytes)
    cursor = tree.walk()
    
    while True:
        node: Node = cursor.node
        node_type = node.type
        
        start_line = node.start_point[0] + 1
        end_line = node.end_point[0] + 1
        source_range = SourceRange(start_line, end_line)
        
        try:
            node_text = node.text.decode('utf8', errors='ignore') 
        except UnicodeDecodeError:
            node_text = "DecodeError"


        # ======================================================
        # 核心逻辑：符号 (Symbol) 识别和记录
        # ======================================================

        # 1. 函数定义 (Function Definition)
        if node_type == 'function_definition':
            declarator = node.child_by_field_name('declarator')
            name_node = None
            if declarator:
                # 寻找函数名，可能在一个 pointer_declarator 或直接的 identifier 里面
                name_node_candidate = declarator
                while name_node_candidate and name_node_candidate.type != 'identifier':
                    # 处理 `(*func_ptr)` 形式，寻找括号内的 identifier
                    if name_node_candidate.type == 'parenthesized_declarator' and len(name_node_candidate.children) > 2:
                        name_node_candidate = name_node_candidate.children[1] # 跳过 (
                    elif name_node_candidate.child_by_field_name('declarator'):
                        name_node_candidate = name_node_candidate.child_by_field_name('declarator')
                    else: # 可能是直接的 identifier
                        break

                if name_node_candidate and name_node_candidate.type == 'identifier':
                    name_node = name_node_candidate
            
            if name_node:
                func_name_short = name_node.text.decode('utf8', errors='ignore')
                
                # 直接记录整个函数定义（包含签名和函数体）到 code 属性
                func_text = node.text.decode('utf8', errors='ignore')
                
                name_hierarchy = NameHierarchy(func_name_short, client.current_context_name())
                symbol_id = client.recordSymbol(
                    name_hierarchy,
                    node_path=file_path,
                    tree_node=node,
                    kind_hint=symbolKindToString(srctrl.SymbolKind.FUNCTION)
                )
                # 写入完整代码文本
                full_name = client.symbolId_to_Name[symbol_id]
                client.symbol_data[full_name]['code'] = func_text
                
                # 标记为用户自定义函数并创建图节点
                client.recordSymbolKind(
                    symbol_id,
                    srctrl.SymbolKind.FUNCTION,
                    {'category': FunctionCategory.USER_DEFINED.value}
                )
                
                # 将作用域范围记录为整个函数（含签名），确保 code 包含签名
                client.recordSymbolScopeLocation(symbol_id, source_range)

                client.push_scope(client.symbolId_to_Name[symbol_id], symbol_id)
                print(f"  [SCOPE] ENTER FUNCTION: {client.symbolId_to_Name[symbol_id]}")
        
        # 2. 局部变量声明 (Local Variable Declaration) - 在函数体内
        # 不再单独记录局部变量，避免冗余信息
        
        # 3. 变量/函数声明 (Global Variable/Function Declaration) & extern 变量 & const 变量
        elif node_type == 'declaration' and node.parent.type == 'translation_unit':
            is_extern = False
            is_const = False
            
            type_node = node.child_by_field_name('type')
            if type_node:
                for child in type_node.children:
                    if child.type == 'storage_class_specifier' and child.text.decode('utf8', errors='ignore') == 'extern':
                        is_extern = True
                    if child.type == 'type_qualifier' and child.text.decode('utf8', errors='ignore') == 'const':
                        is_const = True
            
            declarator = node.child_by_field_name('declarator')
            
            if declarator: 
                if declarator.type == 'function_declarator':
                     # 函数声明处理
                     name_node = None
                     for child in declarator.children:
                         if child.type == 'identifier':
                             name_node = child
                             break
                     if name_node:
                        func_name_short = name_node.text.decode('utf8', errors='ignore')
                        name_hierarchy = NameHierarchy(func_name_short, client.current_context_name())
                        symbol_id = client.recordSymbol(name_hierarchy, node_path=file_path, tree_node=node, kind_hint=symbolKindToString(srctrl.SymbolKind.FUNCTION_DECLARATION)) # <--- 修改
                        client.recordSymbolKind(symbol_id, srctrl.SymbolKind.FUNCTION_DECLARATION) # <--- 修改
                        print(f"  [CLIENT] Recorded FUNCTION_DECLARATION: {client.symbolId_to_Name[symbol_id]} in {file_name}")
                
                elif declarator.type == 'init_declarator' or declarator.type == 'declarator': # 变量声明 (可能带初始化)
                    name_node = None
                    # 寻找 identifier，可能在 pointer_declarator 或 array_declarator 里面
                    name_node_candidate = declarator
                    while name_node_candidate and name_node_candidate.type != 'identifier':
                        if name_node_candidate.child_by_field_name('declarator'):
                            name_node_candidate = name_node_candidate.child_by_field_name('declarator')
                        elif name_node_candidate.type == 'parenthesized_declarator' and len(name_node_candidate.children) > 2:
                            name_node_candidate = name_node_candidate.children[1]
                        elif name_node_candidate.type == 'pointer_declarator':
                            # 处理函数指针：int (*operation)(int a, int b)
                            if name_node_candidate.child_by_field_name('declarator'):
                                name_node_candidate = name_node_candidate.child_by_field_name('declarator')
                            else:
                                break
                        else:
                            break 

                    if name_node_candidate and name_node_candidate.type == 'identifier':
                        name_node = name_node_candidate
                    
                    if name_node:
                        var_name_short = name_node.text.decode('utf8', errors='ignore')
                        
                        
                        if is_extern:
                            full_name, symbol_id = client.resolve_referenced_symbol(var_name_short)
                            # 这里直接修改 symbol_data 的 kind 字符串，不再通过 symbolKindToString 转换
                            client.symbol_data[full_name]['kind'] = symbolKindToString(srctrl.SymbolKind.EXTERNAL_VARIABLE) # <--- 修改
                            client.recordSymbolKind(symbol_id, srctrl.SymbolKind.EXTERNAL_VARIABLE) # <--- 修改
                            current_file_id = client.scope_id_stack[1]
                            client.recordReference(
                                current_file_id, 
                                symbol_id, 
                                srctrl.ReferenceKind.USAGE # <--- 修改
                            )
                            print(f"  [CLIENT] Recorded EXTERNAL_VARIABLE: {full_name} in {file_name}")
                        elif is_const:
                            name_hierarchy = NameHierarchy(var_name_short, client.current_context_name())
                            symbol_id = client.recordSymbol(name_hierarchy, node_path=file_path, tree_node=node, kind_hint=symbolKindToString(srctrl.SymbolKind.GLOBAL_CONSTANT)) # <--- 修改
                            client.recordSymbolKind(symbol_id, srctrl.SymbolKind.GLOBAL_CONSTANT) # <--- 修改
                            print(f"  [CLIENT] Recorded GLOBAL_CONSTANT: {client.symbolId_to_Name[symbol_id]}")
                        else: # 普通全局变量定义
                            name_hierarchy = NameHierarchy(var_name_short, client.current_context_name())
                            symbol_id = client.recordSymbol(name_hierarchy, node_path=file_path, tree_node=node, kind_hint=symbolKindToString(srctrl.SymbolKind.GLOBAL_VARIABLE)) # <--- 修改
                            client.recordSymbolKind(symbol_id, srctrl.SymbolKind.GLOBAL_VARIABLE) # <--- 修改
        
        # 4. 结构体定义 (Struct Definition)
        elif node_type == 'struct_specifier':
            # struct_specifier 可以是 'struct name { ... }' 或 'struct { ... } name;'
            # 或者 'struct name;' (声明)
            name_node = node.child_by_field_name('name') # 获取 struct 的名字
            if name_node:
                struct_name_short = name_node.text.decode('utf8', errors='ignore')
                name_hierarchy = NameHierarchy(struct_name_short, client.current_context_name())
                symbol_id = client.recordSymbol(name_hierarchy, node_path=file_path, tree_node=node, kind_hint=symbolKindToString(srctrl.SymbolKind.STRUCT)) # <--- 修改
                client.recordSymbolKind(symbol_id, srctrl.SymbolKind.STRUCT) # <--- 修改
                
                body_node = node.child_by_field_name('body')
                if body_node: # 有定义体
                    body_start_line = body_node.start_point[0] + 1
                    body_end_line = body_node.end_point[0] + 1
                    client.recordSymbolScopeLocation(symbol_id, SourceRange(body_start_line, body_end_line))
                    
                    # 遍历结构体成员
                    for child in body_node.children:
                        if child.type == 'field_declaration':
                            # 处理结构体成员
                            member_declarator = child.child_by_field_name('declarator')
                            if member_declarator:
                                member_name_node = None
                                # 寻找成员名
                                name_node_candidate = member_declarator
                                while name_node_candidate and name_node_candidate.type != 'identifier':
                                    if name_node_candidate.child_by_field_name('declarator'):
                                        name_node_candidate = name_node_candidate.child_by_field_name('declarator')
                                    elif name_node_candidate.type == 'parenthesized_declarator' and len(name_node_candidate.children) > 2:
                                        name_node_candidate = name_node_candidate.children[1]
                                    else:
                                        break
                                
                                if name_node_candidate and name_node_candidate.type == 'identifier':
                                    member_name_node = name_node_candidate
                                
                                if member_name_node:
                                    member_name_short = member_name_node.text.decode('utf8', errors='ignore')
                                    member_name_hierarchy = NameHierarchy(member_name_short, client.symbolId_to_Name[symbol_id])
                                    member_symbol_id = client.recordSymbol(member_name_hierarchy, node_path=file_path, tree_node=child, kind_hint=symbolKindToString(srctrl.SymbolKind.STRUCT_MEMBER))
                                    client.recordSymbolKind(member_symbol_id, srctrl.SymbolKind.STRUCT_MEMBER)
                                    
                                    # 建立 HAS_MEMBER 关系：STRUCT -> HAS_MEMBER -> STRUCT_MEMBER
                                    client.graphDB.add_edge(
                                        start_label=symbolKindToString(srctrl.SymbolKind.STRUCT),
                                        start_name=client.symbolId_to_Name[symbol_id],
                                        relationship_type='HAS_MEMBER',
                                        end_label=symbolKindToString(srctrl.SymbolKind.STRUCT_MEMBER),
                                        end_name=client.symbolId_to_Name[member_symbol_id],
                                        params={'association_type': 'STRUCT_MEMBER'}
                                    )
                                    print(f"  [CLIENT] Recorded STRUCT_MEMBER: {client.symbolId_to_Name[member_symbol_id]}")
                print(f"  [CLIENT] Recorded STRUCT: {client.symbolId_to_Name[symbol_id]}")

        # 5. 联合体定义 (Union Definition)
        elif node_type == 'union_specifier':
            name_node = node.child_by_field_name('name')
            if name_node:
                union_name_short = name_node.text.decode('utf8', errors='ignore')
                name_hierarchy = NameHierarchy(union_name_short, client.current_context_name())
                symbol_id = client.recordSymbol(name_hierarchy, node_path=file_path, tree_node=node, kind_hint=symbolKindToString(srctrl.SymbolKind.UNION)) # <--- 修改
                client.recordSymbolKind(symbol_id, srctrl.SymbolKind.UNION) # <--- 修改

                body_node = node.child_by_field_name('body')
                if body_node:
                    body_start_line = body_node.start_point[0] + 1
                    body_end_line = body_node.end_point[0] + 1
                    client.recordSymbolScopeLocation(symbol_id, SourceRange(body_start_line, body_end_line))
                print(f"  [CLIENT] Recorded UNION: {client.symbolId_to_Name[symbol_id]}")
        
        # 6. 枚举定义 (Enum Definition)
        elif node_type == 'enum_specifier':
            name_node = node.child_by_field_name('name')
            if name_node:
                enum_name_short = name_node.text.decode('utf8', errors='ignore')
                name_hierarchy = NameHierarchy(enum_name_short, client.current_context_name())
                symbol_id = client.recordSymbol(name_hierarchy, node_path=file_path, tree_node=node, kind_hint=symbolKindToString(srctrl.SymbolKind.ENUM)) # <--- 修改
                client.recordSymbolKind(symbol_id, srctrl.SymbolKind.ENUM) # <--- 修改

                body_node = node.child_by_field_name('body') # 枚举体也可以有花括号体
                if body_node:
                    body_start_line = body_node.start_point[0] + 1
                    body_end_line = body_node.end_point[0] + 1
                    client.recordSymbolScopeLocation(symbol_id, SourceRange(body_start_line, body_end_line))
                    # 遍历 enum_declarator (枚举成员)
                    for child in body_node.children:
                        if child.type == 'enumerator':
                            enum_member_name_node = child.child_by_field_name('name')
                            if enum_member_name_node:
                                member_name_short = enum_member_name_node.text.decode('utf8', errors='ignore')
                                # 枚举成员通常作为宏或常量处理，这里简化为 GLOBAL_CONSTANT
                                member_name_hierarchy = NameHierarchy(member_name_short, client.symbolId_to_Name[symbol_id]) # 父级是枚举本身
                                member_symbol_id = client.recordSymbol(member_name_hierarchy, node_path=file_path, tree_node=child, kind_hint=symbolKindToString(srctrl.SymbolKind.GLOBAL_CONSTANT)) # <--- 修改
                                client.recordSymbolKind(member_symbol_id, srctrl.SymbolKind.GLOBAL_CONSTANT) # <--- 修改
                                # 建立 CONTAINS 关系：ENUM -> CONTAINS -> GLOBAL_CONSTANT (enum member)
                                client.graphDB.add_edge(
                                    start_label=symbolKindToString(srctrl.SymbolKind.ENUM), # <--- 修改
                                    start_name=client.symbolId_to_Name[symbol_id],
                                    relationship_type='CONTAINS',
                                    end_label=symbolKindToString(srctrl.SymbolKind.GLOBAL_CONSTANT), # <--- 修改
                                    end_name=client.symbolId_to_Name[member_symbol_id],
                                    params={'association_type': 'ENUM_MEMBER'}
                                )
                                print(f"  [CLIENT] Recorded ENUM_MEMBER: {client.symbolId_to_Name[member_symbol_id]}")
                print(f"  [CLIENT] Recorded ENUM: {client.symbolId_to_Name[symbol_id]}")

        # 7. typedef 定义 (Typedef Definition)
        elif node_type == 'typedef_declaration':
            # typedef struct { ... } MyStruct;
            # typedef int (*FuncPtr)(int, int);
            # typedef unsigned long size_t;
            declarator = node.child_by_field_name('declarator') # 获取 `typedef` 后面的声明符，也就是新名字

            if declarator:
                typedef_name_node = None
                # 寻找 typedef 的新名字，可能在一个 pointer_declarator 或直接的 identifier 里面
                name_node_candidate = declarator
                while name_node_candidate and name_node_candidate.type not in ['identifier', 'function_declarator']:
                    if name_node_candidate.child_by_field_name('declarator'):
                        name_node_candidate = name_node_candidate.child_by_field_name('declarator')
                    elif name_node_candidate.type == 'parenthesized_declarator' and len(name_node_candidate.children) > 2:
                        name_node_candidate = name_node_candidate.children[1]
                    else:
                        break 

                if name_node_candidate and name_node_candidate.type == 'identifier':
                    typedef_name_node = name_node_candidate
                elif name_node_candidate and name_node_candidate.type == 'function_declarator':
                    # 处理函数指针 typedef: typedef int (*FuncPtr)(int);
                    # FuncPtr 才是 typedef 的名字
                    for child in name_node_candidate.children:
                        if child.type == 'identifier':
                            typedef_name_node = child
                            break
                            
                if typedef_name_node:
                    typedef_name_short = typedef_name_node.text.decode('utf8', errors='ignore')
                    name_hierarchy = NameHierarchy(typedef_name_short, client.current_context_name())
                    
                    kind_hint_str = symbolKindToString(srctrl.SymbolKind.TYPEDEF) # <--- 修改
                    if name_node_candidate.type == 'function_declarator':
                        kind_hint_str = symbolKindToString(srctrl.SymbolKind.GLOBAL_VARIABLE) # 函数指针作为全局变量处理

                    symbol_id = client.recordSymbol(name_hierarchy, node_path=file_path, tree_node=node, kind_hint=kind_hint_str) # <--- 修改
                    if kind_hint_str == symbolKindToString(srctrl.SymbolKind.GLOBAL_VARIABLE): # 函数指针作为全局变量处理
                        client.recordSymbolKind(symbol_id, srctrl.SymbolKind.GLOBAL_VARIABLE)
                    else:
                        client.recordSymbolKind(symbol_id, srctrl.SymbolKind.TYPEDEF) # <--- 修改
                    print(f"  [CLIENT] Recorded {kind_hint_str}: {client.symbolId_to_Name[symbol_id]}") # <--- 修改
        
        # 8. 宏定义 (Macro Definition) - preproc_def
        elif node_type == 'preproc_def':
            name_node = node.child_by_field_name('name')
            if name_node:
                macro_name_short = name_node.text.decode('utf8', errors='ignore')
                name_hierarchy = NameHierarchy(macro_name_short, client.current_context_name())
                symbol_id = client.recordSymbol(name_hierarchy, node_path=file_path, tree_node=node, kind_hint=symbolKindToString(srctrl.SymbolKind.MACRO)) # <--- 修改
                client.recordSymbolKind(symbol_id, srctrl.SymbolKind.MACRO) # <--- 修改
                print(f"  [CLIENT] Recorded MACRO: {client.symbolId_to_Name[symbol_id]}")

        # 9. 函数调用 (Call Expression)
        elif node_type == 'call_expression':
            function_id_node = node.child_by_field_name('function')
            
            if function_id_node and function_id_node.type == 'identifier':
                callee_name_short = function_id_node.text.decode('utf8', errors='ignore')
                
                # 尝试解析现有符号（可能生成一个文件限定的 UNKNOWN 占位）
                referenced_full_name, referenced_symbol_id = client.resolve_referenced_symbol(callee_name_short)

                # 如果是已知的库/系统函数，则确保创建为 FUNCTION，并补充属性
                known_info = KNOWN_FUNCTIONS.get(callee_name_short)
                if known_info:
                    should_create_global = (
                        referenced_full_name not in client.symbol_data or
                        client.symbol_data[referenced_full_name]['kind'] in [
                            symbolKindToString(srctrl.SymbolKind.UNKNOWN),
                            symbolKindToString(srctrl.SymbolKind.FUNCTION_DECLARATION)
                        ]
                    )

                    # 优先采用全局符号名（不带文件前缀）
                    if callee_name_short not in client.global_symbol_definitions:
                        global_id = client.symbol.record_symbol(callee_name_short)
                        client.symbolId_to_Name[global_id] = callee_name_short
                        client.global_symbol_definitions[callee_name_short] = callee_name_short
                        client.global_symbol_ids[callee_name_short] = global_id

                        client.symbol_data[callee_name_short] = {
                            'name': callee_name_short,
                            'path': 'system_library',
                            'kind': symbolKindToString(srctrl.SymbolKind.FUNCTION),
                            'parent_name': known_info.get('header', 'builtins'),
                            'full_name': callee_name_short,
                            'references': []
                        }
                        client.recordSymbolKind(
                            global_id,
                            srctrl.SymbolKind.FUNCTION,
                            {
                                'category': known_info['category'].value,
                                'header': known_info.get('header', ''),
                                'description': known_info.get('description', '')
                            }
                        )

                    # 使用全局函数符号进行引用
                    referenced_full_name = callee_name_short
                    referenced_symbol_id = client.global_symbol_ids[callee_name_short]

                # 记录调用关系
                context_symbol_id = client.current_context_id()
                client.recordReference(
                    context_symbol_id,
                    referenced_symbol_id,
                    srctrl.ReferenceKind.CALL
                )
        
        # 10. Include 引用
        elif node_type == 'preproc_include':
             header_node = node.child_by_field_name('path')
             if header_node:
                raw_header_name = header_node.text.decode('utf8', errors='ignore')
                # 使用标准化路径
                header_name = client.normalize_header_path(raw_header_name)
                
                referenced_symbol_id = client.symbol.record_symbol(header_name)
                client.symbolId_to_Name[referenced_symbol_id] = header_name
                
                if header_name not in client.symbol_data:
                     client.symbol_data[header_name] = {
                        'name': header_name, 
                        'kind': 'HEADER', # <--- HEADER 暂时仍使用字符串字面量，因为它不在 srctrl.SymbolKind 中
                        'parent_name': '', 
                        'full_name': header_name,
                        'references': []
                    }
                     client.graphDB.add_node(label='HEADER', full_name=header_name)

                client.recordReference(
                    client.current_context_id(), 
                    referenced_symbol_id, 
                    srctrl.ReferenceKind.INCLUDE # <--- 修改
                )
        
        # 11. 标识符引用（变量使用、未定义的函数调用等）
        elif node_type == 'identifier':
            # 只在函数体内或某些表达式上下文中处理标识符引用
            # 避免处理定义时的标识符（如函数名、变量名等）
            parent = node.parent
            if parent and parent.type not in [
                'function_definition', 'declaration', 'function_declarator', 
                'init_declarator', 'parameter_declaration', 'declarator',
                'pointer_declarator', 'array_declarator', 'field_declaration',
                'struct_specifier', 'union_specifier', 'enum_specifier',
                'typedef_declaration', 'preproc_def', 'preproc_function_def',
                'enumerator'
            ]:
                # 确保当前作用域是函数（不在文件模块级别）
                if len(client.scope_stack) > 2:  # 至少在函数内
                    identifier_name = node.text.decode('utf8', errors='ignore')
                    
                    # 排除某些关键字和类型名
                    keywords = {'if', 'else', 'while', 'for', 'return', 'int', 'char', 
                               'void', 'float', 'double', 'struct', 'union', 'enum',
                               'sizeof', 'typedef', 'const', 'static', 'extern'}
                    
                    if identifier_name not in keywords:
                        # 检查这是否是一个全局符号的使用
                        if identifier_name in client.global_symbol_definitions:
                            referenced_full_name = client.global_symbol_definitions[identifier_name]
                            referenced_symbol_id = client.global_symbol_ids[identifier_name]
                            
                            # 只记录变量使用，不记录函数调用（函数调用已在 call_expression 中处理）
                            if parent.type != 'call_expression':
                                context_symbol_id = client.current_context_id()
                                client.recordReference(
                                    context_symbol_id,
                                    referenced_symbol_id,
                                    srctrl.ReferenceKind.USAGE
                                )
                
        # ======================================================
        # Tree-sitter 核心遍历逻辑
        # ======================================================
        
        # 尝试进入子节点
        if cursor.goto_first_child():
            continue

        # 如果没有子节点，尝试进入下一个兄弟节点
        if cursor.goto_next_sibling():
            continue

        # 如果没有兄弟节点，回溯到父节点，并尝试父节点的下一个兄弟节点
        while cursor.goto_parent():
            parent_node: Node = cursor.node
            
            # 在退出函数作用域时弹出堆栈
            if parent_node.type == 'function_definition':
                print(f"  [SCOPE] EXIT FUNCTION: {client.current_context_name()}")
                client.pop_scope()
            
            # 尝试父节点的下一个兄弟节点
            if cursor.goto_next_sibling():
                break
        else:
            # 如果回溯到根节点，并且没有下一个兄弟节点，则遍历结束
            break
            
    print("--- 文件分析完成 ---")