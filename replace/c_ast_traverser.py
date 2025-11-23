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


def extract_function_name_from_definition(declarator_node: Node):
    """
    从函数定义的 declarator 节点中提取函数名。
    支持多种情况：
    - 普通函数：int func(int a) {}
    - 函数指针：int (*func)(int a) {}
    - 复杂声明符：int (*(*func)(int))(int) {}
    - 数组返回类型：int (*func[10])(int) {}
    - 各种嵌套的声明符结构
    """
    if not declarator_node:
        return None
    
    # 情况1: 直接是 identifier（理论上不应该出现在函数定义中，但作为兜底）
    if declarator_node.type == 'identifier':
        return declarator_node.text.decode('utf8', errors='ignore')
    
    # 情况2: function_declarator - 最常见的函数定义形式
    # function_declarator 的结构：
    #   declarator (包含函数名)
    #   parameter_list
    if declarator_node.type == 'function_declarator':
        nested_declarator = declarator_node.child_by_field_name('declarator')
        if nested_declarator:
            # 如果 nested_declarator 直接是 identifier，直接返回
            if nested_declarator.type == 'identifier':
                return nested_declarator.text.decode('utf8', errors='ignore')
            # 否则递归查找函数名
            result = extract_function_name_from_definition(nested_declarator)
            if result:
                return result
        # 如果通过 declarator 字段没找到，尝试在所有子节点中查找 identifier
        # （某些特殊情况可能直接在 function_declarator 的子节点中有 identifier）
        for child in declarator_node.children:
            if child.type == 'identifier':
                return child.text.decode('utf8', errors='ignore')
    
    # 情况3: parenthesized_declarator - 括号声明符，如 (*func) 或 (func)
    if declarator_node.type == 'parenthesized_declarator':
        # 括号内应该有一个 declarator
        if len(declarator_node.children) > 2:
            inner_declarator = declarator_node.children[1]  # 跳过 '('
            return extract_function_name_from_definition(inner_declarator)
    
    # 情况4: pointer_declarator - 指针声明符，如 *func
    if declarator_node.type == 'pointer_declarator':
        nested_declarator = declarator_node.child_by_field_name('declarator')
        if nested_declarator:
            return extract_function_name_from_definition(nested_declarator)
        # 如果没有 declarator 字段，尝试在子节点中查找
        for child in declarator_node.children:
            result = extract_function_name_from_definition(child)
            if result:
                return result
    
    # 情况5: array_declarator - 数组声明符，如 func[10]
    if declarator_node.type == 'array_declarator':
        nested_declarator = declarator_node.child_by_field_name('declarator')
        if nested_declarator:
            return extract_function_name_from_definition(nested_declarator)
    
    # 情况6: init_declarator - 初始化声明符（通常用于变量，但可能出现在某些上下文中）
    if declarator_node.type == 'init_declarator':
        nested_declarator = declarator_node.child_by_field_name('declarator')
        if nested_declarator:
            return extract_function_name_from_definition(nested_declarator)
    
    # 情况7: 如果当前节点有 declarator 字段，递归查找
    if declarator_node.child_by_field_name('declarator'):
        nested_declarator = declarator_node.child_by_field_name('declarator')
        result = extract_function_name_from_definition(nested_declarator)
        if result:
            return result
    
    # 情况8: 在所有子节点中递归查找 identifier
    # 这是最后的兜底策略，处理所有未预料的嵌套结构
    for child in declarator_node.children:
        if child.type == 'identifier':
            return child.text.decode('utf8', errors='ignore')
        # 递归查找子节点
        result = extract_function_name_from_definition(child)
        if result:
            return result
    
    return None


def extract_function_name_from_call(function_node: Node):
    """
    从函数调用节点中提取函数名。
    支持多种情况：
    - 直接调用：func()
    - 指针调用：(*func_ptr)()
    - 成员调用：obj.func()
    - 数组索引：func_array[0]()
    - 复杂表达式：(*ptr).func()
    """
    if not function_node:
        return None
    
    # 情况1: 直接是 identifier
    if function_node.type == 'identifier':
        return function_node.text.decode('utf8', errors='ignore')
    
    # 情况2: 字段表达式 obj.func 或 obj->func
    if function_node.type == 'field_expression':
        field_node = function_node.child_by_field_name('field')
        if field_node and field_node.type == 'identifier':
            return field_node.text.decode('utf8', errors='ignore')
    
    # 情况3: 指针解引用 (*func_ptr) 或 *func_ptr
    if function_node.type == 'pointer_expression' or function_node.type == 'unary_expression':
        # 查找内部的 identifier
        for child in function_node.children:
            if child.type == 'identifier':
                return child.text.decode('utf8', errors='ignore')
            # 递归查找
            result = extract_function_name_from_call(child)
            if result:
                return result
    
    # 情况4: 括号表达式 (func_ptr)
    if function_node.type == 'parenthesized_expression':
        if len(function_node.children) > 1:
            inner_node = function_node.children[1]  # 跳过 '('
            return extract_function_name_from_call(inner_node)
    
    # 情况5: 数组下标 func_array[0]
    if function_node.type == 'subscript_expression':
        array_node = function_node.child_by_field_name('array')
        if array_node:
            return extract_function_name_from_call(array_node)
    
    # 情况6: 复合表达式，递归查找所有子节点
    for child in function_node.children:
        result = extract_function_name_from_call(child)
        if result:
            return result
    
    return None


def extract_function_return_type(function_node: Node):
    """
    从函数定义或声明节点中提取返回类型。
    函数定义的结构：type declarator body
    函数声明的结构：type declarator;
    """
    if not function_node:
        return None
    
    # 支持 function_definition 和 declaration 两种节点类型
    if function_node.type not in ['function_definition', 'declaration']:
        return None
    
    type_node = function_node.child_by_field_name('type')
    if not type_node:
        return 'void'  # 默认返回类型
    
    # 提取类型文本
    return_type_text = type_node.text.decode('utf8', errors='ignore').strip()
    return return_type_text if return_type_text else 'void'


def extract_function_parameters(function_node: Node):
    """
    从函数定义节点中提取参数列表。
    返回参数列表的字符串表示，格式如: "int a, char *b, void"
    """
    if not function_node:
        return []
    
    # 获取 declarator
    declarator = None
    if function_node.type == 'function_definition':
        declarator = function_node.child_by_field_name('declarator')
    elif function_node.type == 'declaration':
        declarator = function_node.child_by_field_name('declarator')
    
    if not declarator:
        return []
    
    # 查找 function_declarator
    def find_function_declarator(n, depth=0, max_depth=10):
        """递归查找 function_declarator 节点"""
        if depth > max_depth:
            return None
        if n.type == 'function_declarator':
            return n
        for child in n.children:
            result = find_function_declarator(child, depth + 1, max_depth)
            if result:
                return result
        return None
    
    func_declarator = find_function_declarator(declarator)
    if not func_declarator:
        return []
    
    # 获取 parameter_list
    param_list = func_declarator.child_by_field_name('parameters')
    if not param_list:
        return []
    
    # 提取参数
    parameters = []
    for child in param_list.children:
        if child.type == 'parameter_declaration':
            # 提取参数类型和名称
            param_type_node = child.child_by_field_name('type')
            param_declarator = child.child_by_field_name('declarator')
            
            param_type = param_type_node.text.decode('utf8', errors='ignore').strip() if param_type_node else ''
            
            # 提取参数名
            param_name = None
            if param_declarator:
                # 查找 identifier
                def find_identifier_in_declarator(n, depth=0, max_depth=5):
                    if depth > max_depth:
                        return None
                    if n.type == 'identifier':
                        return n.text.decode('utf8', errors='ignore')
                    for c in n.children:
                        result = find_identifier_in_declarator(c, depth + 1, max_depth)
                        if result:
                            return result
                    return None
                
                param_name = find_identifier_in_declarator(param_declarator)
            
            # 构建参数字符串
            if param_name:
                param_str = f"{param_type} {param_name}".strip()
            else:
                param_str = param_type if param_type else 'void'
            
            if param_str:
                parameters.append(param_str)
        elif child.type == 'variadic_parameter':
            parameters.append('...')
    
    return parameters


def traverse_c_ast_and_record(client: AstVisitorClient, file_path: str):
    """
    解析 C 代码文件并使用 Tree-sitter 的 cursor 进行深度优先遍历，
    将提取的信息记录到 AstVisitorClient 中。
    """
    parser = setup_c_parser()

    # print(f"\n--- 开始分析文件: {file_path} ---")

    try:
        with open(file_path, 'rb') as f: 
            c_code_bytes = f.read()
    except FileNotFoundError:
        # print(f"  [ERROR] File not found: {file_path}")
        return
    except Exception as e:
        # print(f"  [ERROR] Failed to read file {file_path}: {e}")
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
            # 检查是否有函数体（body），只有真正的函数定义才有 body
            body_node = node.child_by_field_name('body')
            if not body_node:
                # 如果没有 body，这可能是函数声明被误解析，跳过处理
                # 函数声明会在后面的 declaration 节点中处理
                print(f"  [WARNING] 没有函数体，跳过处理")
                pass
            else:
                # print(f"  有函数体:{body_node.text.decode('utf8', errors='ignore')[:100]}，继续处理")
                declarator = node.child_by_field_name('declarator')
                
                # 使用专门的辅助函数提取函数名，支持各种复杂的声明符结构
                func_name_short = extract_function_name_from_definition(declarator) if declarator else None
                
                # 如果提取失败，添加调试信息并使用兜底方法
                if not func_name_short:
                    def find_identifier_in_node(n, depth=0, max_depth=10):
                        """在所有子节点中递归查找 identifier（作为函数名）"""
                        if depth > max_depth:
                            return None
                        if n.type == 'identifier':
                            # 检查这个 identifier 是否在 function_declarator 的 declarator 字段中
                            # 或者在其他合理的上下文中
                            return n.text.decode('utf8', errors='ignore')
                        for child in n.children:
                            result = find_identifier_in_node(child, depth + 1, max_depth)
                            if result:
                                return result
                        return None
                    
                    if declarator:
                        # print(f"  [WARNING] 无法提取函数名，declarator.type = {declarator.type}")
                        # print(f"  [WARNING] declarator.text = {declarator.text.decode('utf8', errors='ignore')[:100]}")
                        # 尝试直接在所有子节点中查找 identifier
                        func_name_short = find_identifier_in_node(declarator)
                        # if func_name_short:
                        #     print(f"  [WARNING] 通过兜底方法找到函数名: {func_name_short}")
                    else:
                        # print(f"  [WARNING] function_definition 没有 declarator 字段")
                        # 如果连 declarator 都没有，尝试在整个节点中查找
                        func_name_short = find_identifier_in_node(node)
                        # if func_name_short:
                        #     print(f"  [WARNING] 通过全局搜索找到函数名: {func_name_short}")
                
                if func_name_short:
                    
                    # 直接记录整个函数定义（包含签名和函数体）到 code 属性
                    func_text = node.text.decode('utf8', errors='ignore')
                    
                    # 提取返回类型和参数列表
                    return_type = extract_function_return_type(node)
                    parameters = extract_function_parameters(node)
                    
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
                    
                    # 标记为用户自定义函数并创建图节点，包含返回类型和参数列表
                    attributes = {
                        'category': FunctionCategory.USER_DEFINED.value,
                        'return_type': return_type,
                        'parameters': parameters
                    }
                    client.recordSymbolKind(
                        symbol_id,
                        srctrl.SymbolKind.FUNCTION,
                        attributes
                    )
                    
                    # 将作用域范围记录为整个函数（含签名），确保 code 包含签名
                    client.recordSymbolScopeLocation(symbol_id, source_range)

                    client.push_scope(client.symbolId_to_Name[symbol_id], symbol_id)
                    # 只在成功识别函数时输出函数名
                    # print(f"识别到函数: {func_name_short}")
                    # print(f"  [SCOPE] ENTER FUNCTION: {client.symbolId_to_Name[symbol_id]}")
        
        # 2. 局部变量声明 (Local Variable Declaration) - 在函数体内
        # 不再单独记录局部变量，避免冗余信息
        
        # 3. 变量/函数声明 (Global Variable/Function Declaration) & extern 变量 & const 变量
        # 对于包含函数体的 declaration 节点，即使不在 translation_unit 层级，也应该被识别为函数定义
        elif node_type == 'declaration':
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
                # 先尝试提取函数名，检查是否是函数声明
                # 函数声明的特征：declarator 中包含 function_declarator（有参数列表）
                def has_function_declarator(n, depth=0, max_depth=10):
                    """递归检查节点或其子节点中是否包含 function_declarator"""
                    if depth > max_depth:
                        return False
                    if n.type == 'function_declarator':
                        return True
                    for child in n.children:
                        if has_function_declarator(child, depth + 1, max_depth):
                            return True
                    return False
                
                # 检查是否是函数声明（包含 function_declarator）
                is_function_declaration = has_function_declarator(declarator)
                
                if is_function_declaration:
                    # 检查是否包含函数体（body），如果有，则是函数定义，不是函数声明
                    # 函数体可能在 declarator 的 function_declarator 中，或者在整个 declaration 节点中
                    def has_function_body(n, depth=0, max_depth=10):
                        """递归检查节点或其子节点中是否包含函数体（compound_statement）"""
                        if depth > max_depth:
                            return False
                        # 检查当前节点是否是 compound_statement（函数体）
                        if n.type == 'compound_statement':
                            return True
                        # 检查是否有 body 字段
                        if n.child_by_field_name('body'):
                            return True
                        for child in n.children:
                            if has_function_body(child, depth + 1, max_depth):
                                return True
                        return False
                    
                    has_body = has_function_body(node)
                    
                    if has_body:
                        # 这是函数定义，不是函数声明
                        func_name_short = extract_function_name_from_definition(declarator)
                        if func_name_short:
                            # 提取完整的函数定义文本（包括返回类型、函数名、参数列表和函数体）
                            func_text = node.text.decode('utf8', errors='ignore')
                            
                            # 提取返回类型和参数列表
                            return_type = extract_function_return_type(node)
                            parameters = extract_function_parameters(node)
                            
                            name_hierarchy = NameHierarchy(func_name_short, client.current_context_name())
                            symbol_id = client.recordSymbol(name_hierarchy, node_path=file_path, tree_node=node, kind_hint=symbolKindToString(srctrl.SymbolKind.FUNCTION)) # <--- 修改
                            
                            # 将完整的函数定义文本存储到 code 属性
                            full_name = client.symbolId_to_Name[symbol_id]
                            client.symbol_data[full_name]['code'] = func_text
                            
                            # 提取函数签名（不包括函数体）
                            # 查找 compound_statement 的开始位置
                            body_node = None
                            for child in node.children:
                                if child.type == 'compound_statement' or has_function_body(child):
                                    body_node = child
                                    break
                            
                            if body_node:
                                # 函数签名是函数定义文本减去函数体
                                func_text_bytes = node.text
                                body_start = body_node.start_byte - node.start_byte
                                signature_text = func_text_bytes[:body_start].decode('utf8', errors='ignore').strip()
                            else:
                                signature_text = func_text
                            
                            client.symbol_data[full_name]['signature'] = signature_text
                            
                            # 创建属性字典，包含返回类型和参数列表
                            attributes = {
                                'signature': signature_text,
                                'return_type': return_type,
                                'parameters': parameters
                            }
                            client.recordSymbolKind(symbol_id, srctrl.SymbolKind.FUNCTION, attributes) # <--- 修改
                            
                            # 记录函数的作用域位置
                            client.recordSymbolScopeLocation(symbol_id, source_range)
                            
                            # 进入函数作用域
                            client.enter_scope(symbol_id, srctrl.SymbolKind.FUNCTION)
                            # print(f"  [CLIENT] Recorded FUNCTION: {client.symbolId_to_Name[symbol_id]} in {file_name}")
                    else:
                        # 函数声明处理 - 使用专门的辅助函数提取函数名
                        func_name_short = extract_function_name_from_definition(declarator)
                        if func_name_short:
                            # print(f"  函数声明: {func_name_short}")
                            # 提取完整的函数声明文本（包括返回类型、函数名、参数列表）
                            declaration_text = node.text.decode('utf8', errors='ignore')
                            
                            # 提取返回类型和参数列表
                            return_type = extract_function_return_type(node)
                            parameters = extract_function_parameters(node)
                            
                            name_hierarchy = NameHierarchy(func_name_short, client.current_context_name())
                            symbol_id = client.recordSymbol(name_hierarchy, node_path=file_path, tree_node=node, kind_hint=symbolKindToString(srctrl.SymbolKind.FUNCTION_DECLARATION)) # <--- 修改
                            
                            # 将完整的函数声明文本存储到 code 属性
                            full_name = client.symbolId_to_Name[symbol_id]
                            client.symbol_data[full_name]['code'] = declaration_text
                            
                            # 创建属性字典，包含返回类型和参数列表
                            attributes = {
                                'return_type': return_type,
                                'parameters': parameters
                            }
                            client.recordSymbolKind(symbol_id, srctrl.SymbolKind.FUNCTION_DECLARATION, attributes) # <--- 修改
                            # print(f"  [CLIENT] Recorded FUNCTION_DECLARATION: {client.symbolId_to_Name[symbol_id]} in {file_name}")
                
                elif declarator.type == 'init_declarator' or declarator.type == 'declarator': # 变量声明 (可能带初始化)
                    # 只处理全局变量声明（在 translation_unit 层级），跳过局部变量
                    if node.parent and node.parent.type != 'translation_unit':
                        pass  # 跳过局部变量声明
                    else:
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
                                # print(f"  [CLIENT] Recorded EXTERNAL_VARIABLE: {full_name} in {file_name}")
                            elif is_const:
                                name_hierarchy = NameHierarchy(var_name_short, client.current_context_name())
                                symbol_id = client.recordSymbol(name_hierarchy, node_path=file_path, tree_node=node, kind_hint=symbolKindToString(srctrl.SymbolKind.GLOBAL_CONSTANT)) # <--- 修改
                                client.recordSymbolKind(symbol_id, srctrl.SymbolKind.GLOBAL_CONSTANT) # <--- 修改
                                # print(f"  [CLIENT] Recorded GLOBAL_CONSTANT: {client.symbolId_to_Name[symbol_id]}")
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
                                    # print(f"  [CLIENT] Recorded STRUCT_MEMBER: {client.symbolId_to_Name[member_symbol_id]}")
                # print(f"  [CLIENT] Recorded STRUCT: {client.symbolId_to_Name[symbol_id]}")

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
                # print(f"  [CLIENT] Recorded UNION: {client.symbolId_to_Name[symbol_id]}")
        
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
                                # print(f"  [CLIENT] Recorded ENUM_MEMBER: {client.symbolId_to_Name[member_symbol_id]}")
                # print(f"  [CLIENT] Recorded ENUM: {client.symbolId_to_Name[symbol_id]}")

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
                    # print(f"  [CLIENT] Recorded {kind_hint_str}: {client.symbolId_to_Name[symbol_id]}") # <--- 修改
        
        # 8. 宏定义 (Macro Definition) - preproc_def
        elif node_type == 'preproc_def':
            name_node = node.child_by_field_name('name')
            if name_node:
                macro_name_short = name_node.text.decode('utf8', errors='ignore')
                name_hierarchy = NameHierarchy(macro_name_short, client.current_context_name())
                symbol_id = client.recordSymbol(name_hierarchy, node_path=file_path, tree_node=node, kind_hint=symbolKindToString(srctrl.SymbolKind.MACRO)) # <--- 修改
                client.recordSymbolKind(symbol_id, srctrl.SymbolKind.MACRO) # <--- 修改
                # print(f"  [CLIENT] Recorded MACRO: {client.symbolId_to_Name[symbol_id]}")

        # 9. 函数调用 (Call Expression)
        elif node_type == 'call_expression':
            function_id_node = node.child_by_field_name('function')
            
            # 使用辅助函数提取函数名，支持各种复杂情况
            callee_name_short = extract_function_name_from_call(function_id_node)
            
            if callee_name_short:
                # 尝试解析现有符号（可能生成一个文件限定的 UNKNOWN 占位）
                referenced_full_name, referenced_symbol_id = client.resolve_referenced_symbol(callee_name_short)

                # 如果是已知的库/系统函数，则确保创建为 FUNCTION，并补充属性
                # 注意：只在真正调用时才创建库函数节点，不预先创建
                known_info = KNOWN_FUNCTIONS.get(callee_name_short)
                if known_info:
                    # 优先采用全局符号名（不带文件前缀）
                    # 只在第一次遇到此库函数调用时创建节点
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
                # print(f"  [SCOPE] EXIT FUNCTION: {client.current_context_name()}")
                client.pop_scope()
            
            # 尝试父节点的下一个兄弟节点
            if cursor.goto_next_sibling():
                break
        else:
            # 如果回溯到根节点，并且没有下一个兄弟节点，则遍历结束
            break
            
    # print("--- 文件分析完成 ---")