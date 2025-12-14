#!/usr/bin/env python3
"""
C 语言测试数据集生成器
生成常见的 C 语言 Bug 示例用于评估 CodexGraph
"""

import json
from pathlib import Path
from typing import List, Dict


class CTestDatasetGenerator:
    """C 语言测试数据集生成器"""
    
    def __init__(self):
        self.instances: List[Dict] = []
    
    def add_instance(self, **kwargs):
        """添加测试实例"""
        self.instances.append(kwargs)
    
    def save(self, output_file: str):
        """保存为 JSON"""
        Path(output_file).parent.mkdir(parents=True, exist_ok=True)
        
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(self.instances, f, indent=2, ensure_ascii=False)
        
        print(f"✅ 已生成 {len(self.instances)} 个测试用例，保存至 {output_file}")


def generate_c_test_dataset() -> CTestDatasetGenerator:
    """生成 C 语言测试数据集"""
    
    gen = CTestDatasetGenerator()
    
    # 1. 空指针解引用
    gen.add_instance(
        instance_id='c_null_ptr_001',
        repo='example_c_project',
        problem_statement='函数未检查指针参数是否为 NULL，导致在访问指针时发生段错误。需要添加 NULL 检查。',
        bug_type='null_pointer_dereference',
        buggy_code='''
#include <stdio.h>

void print_value(int *ptr) {
    // Bug: 直接解引用指针，未检查是否为 NULL
    printf("Value: %d\\n", *ptr);
}

int main() {
    print_value(NULL);  // 这会导致段错误
    return 0;
}
''',
        fixed_code='''
#include <stdio.h>
#include <stddef.h>

void print_value(int *ptr) {
    // Fix: 添加 NULL 检查
    if (ptr == NULL) {
        printf("Error: NULL pointer passed\\n");
        return;
    }
    printf("Value: %d\\n", *ptr);
}

int main() {
    print_value(NULL);  // 现在安全处理
    return 0;
}
''',
        test_code='''
#include <stdio.h>
#include <assert.h>

void print_value(int *ptr);

void test_null_ptr() {
    // 应该安全处理 NULL
    print_value(NULL);
}

void test_valid_ptr() {
    int x = 42;
    print_value(&x);
}

int main() {
    test_null_ptr();
    test_valid_ptr();
    printf("All tests passed!\\n");
    return 0;
}
'''
    )
    
    # 2. 缓冲区溢出
    gen.add_instance(
        instance_id='c_buffer_overflow_001',
        repo='example_c_project',
        problem_statement='字符串复制函数使用不安全的 strcpy，可能导致缓冲区溢出。应该使用 strncpy 或其他安全函数。',
        bug_type='buffer_overflow',
        buggy_code='''
#include <stdio.h>
#include <string.h>

void copy_string(char *dest, const char *src) {
    // Bug: strcpy 不检查目标缓冲区大小
    strcpy(dest, src);
}

int main() {
    char buffer[10];
    copy_string(buffer, "This is a very long string that will overflow");
    return 0;
}
''',
        fixed_code='''
#include <stdio.h>
#include <string.h>

void copy_string(char *dest, size_t dest_size, const char *src) {
    // Fix: 使用 strncpy 限制复制长度
    strncpy(dest, src, dest_size - 1);
    dest[dest_size - 1] = '\\0';  // 确保空终止
}

int main() {
    char buffer[10];
    copy_string(buffer, sizeof(buffer), "This is a very long string");
    printf("Copied: %s\\n", buffer);
    return 0;
}
''',
        test_code='''
#include <stdio.h>
#include <string.h>
#include <assert.h>

void copy_string(char *dest, size_t dest_size, const char *src);

void test_buffer_copy() {
    char buffer[10];
    copy_string(buffer, sizeof(buffer), "Hello");
    assert(strlen(buffer) < sizeof(buffer));
    printf("Test passed: %s\\n", buffer);
}

int main() {
    test_buffer_copy();
    return 0;
}
'''
    )
    
    # 3. 内存泄漏
    gen.add_instance(
        instance_id='c_memory_leak_001',
        repo='example_c_project',
        problem_statement='函数分配内存但在错误路径上未释放，导致内存泄漏。需要确保所有分配的内存都被释放。',
        bug_type='memory_leak',
        buggy_code='''
#include <stdlib.h>
#include <stdio.h>

int* allocate_array(int size) {
    int *arr = (int *)malloc(size * sizeof(int));
    if (arr == NULL) {
        printf("Allocation failed\\n");
        return NULL;  // Bug: 分配失败时资源处理不当
    }
    return arr;
}

void process_array(int size) {
    int *data = allocate_array(size);
    if (data == NULL) {
        return;  // Bug: 这里忘记处理资源
    }
    
    // 处理数据
    printf("Processing %d elements\\n", size);
    
    // Bug: 在所有返回路径上都应该释放内存
    free(data);
}

int main() {
    process_array(100);
    return 0;
}
''',
        fixed_code='''
#include <stdlib.h>
#include <stdio.h>

int* allocate_array(int size) {
    int *arr = (int *)malloc(size * sizeof(int));
    return arr;  // 让调用者检查是否为 NULL
}

void process_array(int size) {
    int *data = allocate_array(size);
    if (data == NULL) {
        printf("Allocation failed\\n");
        return;
    }
    
    printf("Processing %d elements\\n", size);
    
    free(data);  // Fix: 确保释放内存
}

int main() {
    process_array(100);
    return 0;
}
''',
        test_code='''
#include <stdlib.h>
#include <stdio.h>

void process_array(int size);

void test_memory_management() {
    // 多次调用以检查内存泄漏
    for (int i = 0; i < 10; i++) {
        process_array(100);
    }
    printf("Memory test passed\\n");
}

int main() {
    test_memory_management();
    return 0;
}
'''
    )
    
    # 4. 未初始化变量
    gen.add_instance(
        instance_id='c_uninitialized_var_001',
        repo='example_c_project',
        problem_statement='变量在使用前未初始化，导致使用未定义的值。需要在声明时初始化或在使用前赋值。',
        bug_type='uninitialized_variable',
        buggy_code='''
#include <stdio.h>

int calculate_sum(int *arr, int size) {
    int sum;  // Bug: sum 未初始化
    
    for (int i = 0; i < size; i++) {
        sum += arr[i];  // 使用未初始化的变量
    }
    
    return sum;
}

int main() {
    int data[] = {1, 2, 3, 4, 5};
    printf("Sum: %d\\n", calculate_sum(data, 5));
    return 0;
}
''',
        fixed_code='''
#include <stdio.h>

int calculate_sum(int *arr, int size) {
    int sum = 0;  // Fix: 初始化为 0
    
    for (int i = 0; i < size; i++) {
        sum += arr[i];
    }
    
    return sum;
}

int main() {
    int data[] = {1, 2, 3, 4, 5};
    printf("Sum: %d\\n", calculate_sum(data, 5));
    return 0;
}
''',
        test_code='''
#include <stdio.h>
#include <assert.h>

int calculate_sum(int *arr, int size);

void test_sum_calculation() {
    int data[] = {1, 2, 3, 4, 5};
    int result = calculate_sum(data, 5);
    assert(result == 15);  // 1+2+3+4+5 = 15
    printf("Sum test passed: %d\\n", result);
}

int main() {
    test_sum_calculation();
    return 0;
}
'''
    )
    
    # 5. Off-by-one 错误
    gen.add_instance(
        instance_id='c_off_by_one_001',
        repo='example_c_project',
        problem_statement='数组索引循环边界条件错误，导致访问越界或遗漏最后一个元素。需要修正循环条件。',
        bug_type='off_by_one',
        buggy_code='''
#include <stdio.h>

void print_array(int *arr, int size) {
    // Bug: 循环应该到 i < size，而不是 i <= size
    for (int i = 0; i <= size; i++) {
        printf("arr[%d] = %d\\n", i, arr[i]);
    }
}

int main() {
    int data[] = {10, 20, 30, 40, 50};
    print_array(data, 5);  // 这会导致访问数组越界
    return 0;
}
''',
        fixed_code='''
#include <stdio.h>

void print_array(int *arr, int size) {
    // Fix: 使用正确的循环条件
    for (int i = 0; i < size; i++) {
        printf("arr[%d] = %d\\n", i, arr[i]);
    }
}

int main() {
    int data[] = {10, 20, 30, 40, 50};
    print_array(data, 5);
    return 0;
}
''',
        test_code='''
#include <stdio.h>

void print_array(int *arr, int size);

void test_array_loop() {
    int data[] = {10, 20, 30, 40, 50};
    print_array(data, 5);
    printf("Loop test passed\\n");
}

int main() {
    test_array_loop();
    return 0;
}
'''
    )
    
    # 6. 类型不匹配
    gen.add_instance(
        instance_id='c_type_error_001',
        repo='example_c_project',
        problem_statement='函数调用时传递了类型不匹配的参数，如将 int 指针传给期望 char 指针的函数。',
        bug_type='type_error',
        buggy_code='''
#include <stdio.h>
#include <string.h>

int get_length(char *str) {
    return strlen(str);
}

int main() {
    int *ptr = NULL;
    // Bug: 传递 int 指针给期望 char 指针的函数
    printf("Length: %d\\n", get_length((char *)ptr));
    return 0;
}
''',
        fixed_code='''
#include <stdio.h>
#include <string.h>

int get_length(const char *str) {
    if (str == NULL) {
        return 0;
    }
    return strlen(str);
}

int main() {
    const char *str = "Hello";
    // Fix: 传递正确类型的参数
    printf("Length: %d\\n", get_length(str));
    return 0;
}
''',
        test_code='''
#include <stdio.h>

int get_length(const char *str);

void test_string_length() {
    int len = get_length("Hello");
    printf("String length test: %d\\n", len);
}

int main() {
    test_string_length();
    return 0;
}
'''
    )
    
    return gen


def main():
    """主函数"""
    print("🔧 生成 C 语言测试数据集...")
    
    gen = generate_c_test_dataset()
    output_file = 'c_lang_test_dataset.json'
    gen.save(output_file)
    
    print(f"\n✅ 数据集生成完成！")
    print(f"📊 生成了 {len(gen.instances)} 个测试用例")
    print(f"📁 文件位置: {output_file}")
    print(f"\n使用以下命令进行评估:")
    print(f"  python scripts/evaluate_c_lang.py --dataset {output_file} --max-instances 5")


if __name__ == '__main__':
    main()
