"""
测试脚本：分析为什么某些函数不能被识别
"""

import tree_sitter_c as tsc
from tree_sitter import Language, Parser

def setup_parser():
    """设置 C 语言解析器"""
    C_LANGUAGE = Language(tsc.language())
    parser = Parser(C_LANGUAGE)
    return parser

def analyze_function(code, func_name):
    """分析函数的 AST 结构"""
    parser = setup_parser()
    tree = parser.parse(bytes(code, 'utf8'))
    root_node = tree.root_node
    
    print(f"\n{'='*70}")
    print(f"分析函数: {func_name}")
    print(f"{'='*70}")
    print(f"\n源代码:\n{code}\n")
    
    def print_node(node, indent=0):
        """递归打印节点信息"""
        prefix = "  " * indent
        node_type = node.type
        node_text = node.text.decode('utf8', errors='ignore')[:50]  # 限制长度
        print(f"{prefix}{node_type}: {node_text}")
        
        # 如果是 function_definition，详细分析
        if node_type == 'function_definition':
            print(f"{prefix}  [FUNCTION_DEFINITION 详细信息]")
            declarator = node.child_by_field_name('declarator')
            if declarator:
                print(f"{prefix}    declarator.type = {declarator.type}")
                print(f"{prefix}    declarator.text = {declarator.text.decode('utf8', errors='ignore')[:100]}")
                
                # 检查 declarator 的子节点
                print(f"{prefix}    declarator.children:")
                for i, child in enumerate(declarator.children):
                    print(f"{prefix}      [{i}] {child.type}: {child.text.decode('utf8', errors='ignore')[:50]}")
                
                # 如果 declarator 是 function_declarator，检查其 declarator 字段
                if declarator.type == 'function_declarator':
                    nested_declarator = declarator.child_by_field_name('declarator')
                    if nested_declarator:
                        print(f"{prefix}    nested_declarator.type = {nested_declarator.type}")
                        print(f"{prefix}    nested_declarator.text = {nested_declarator.text.decode('utf8', errors='ignore')[:100]}")
                        print(f"{prefix}    nested_declarator.children:")
                        for i, child in enumerate(nested_declarator.children):
                            print(f"{prefix}      [{i}] {child.type}: {child.text.decode('utf8', errors='ignore')[:50]}")
        
        # 递归处理子节点（限制深度）
        if indent < 3:
            for child in node.children:
                print_node(child, indent + 1)
    
    print_node(root_node)
    
    # 查找 function_definition 节点
    def find_function_definitions(node):
        """查找所有 function_definition 节点"""
        functions = []
        if node.type == 'function_definition':
            functions.append(node)
        for child in node.children:
            functions.extend(find_function_definitions(child))
        return functions
    
    functions = find_function_definitions(root_node)
    print(f"\n找到 {len(functions)} 个函数定义")
    
    for i, func in enumerate(functions, 1):
        declarator = func.child_by_field_name('declarator')
        if declarator:
            print(f"\n函数 {i} 的 declarator 结构:")
            print(f"  类型: {declarator.type}")
            print(f"  文本: {declarator.text.decode('utf8', errors='ignore')}")
            
            # 尝试提取函数名
            from c_ast_traverser import extract_function_name_from_definition
            func_name_extracted = extract_function_name_from_definition(declarator)
            print(f"  提取的函数名: {func_name_extracted if func_name_extracted else '未找到'}")

if __name__ == "__main__":
    # 测试函数 1: show_time (能被识别)
    code1 = """static void
show_time( time_t t, int gmt )
    {
    struct tm* tmP;
    char tbuf[500];

    if ( gmt )
	tmP = gmtime( &t );
    else
	tmP = localtime( &t );
    if ( strftime( tbuf, sizeof(tbuf), timefmt, tmP ) > 0 )
	(void) fputs( tbuf, stdout );
    }"""
    
    # 测试函数 2: not_permitted (不能被识别)
    code2 = """static void
not_permitted( char* directive, char* tag, char* val )
    {
    char* title = "Not Permitted";

    (void) printf( "\\
<HR><H2>%s</H2>\\
The filename requested in the %s %s=%s directive\\
may not be fetched.\\
<HR>\\
", title, directive, tag, val );
    }"""
    
    analyze_function(code1, "show_time")
    analyze_function(code2, "not_permitted")

