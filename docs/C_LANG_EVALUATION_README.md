# C 语言 CodexGraph 评估使用指南

## 📖 概述

本指南展示如何使用改进的 CodexGraph（支持 C 语言）在 Multi-SWE-Bench 框架上进行调试性能评估。

## 🚀 快速开始

### 步骤 1：生成 C 语言测试数据集

```bash
python scripts/generate_c_dataset.py
```

这将生成 `c_lang_test_dataset.json`，包含 6 个典型的 C 语言 Bug 示例：
- ✅ 空指针解引用 (NULL pointer dereference)
- ✅ 缓冲区溢出 (Buffer overflow)
- ✅ 内存泄漏 (Memory leak)
- ✅ 未初始化变量 (Uninitialized variable)
- ✅ Off-by-one 错误
- ✅ 类型不匹配 (Type error)

### 步骤 2：运行评估

#### 2.1 快速测试（5 个实例）

```bash
python scripts/evaluate_c_lang.py \
    --dataset c_lang_test_dataset.json \
    --max-instances 5 \
    --work-dir ./c_eval_test \
    --c-standard c11
```

**输出示例：**
```
C 语言 SWE-Bench 评估摘要
================================================================================
C 标准: c11
编译器: gcc
--------------------------------------------------------------------------------
total_instances                : 5
debug_success_count            : 4
debug_success_rate             : 80.00%
compile_success_count          : 5
compile_success_rate           : 100.00%
test_pass_count                : 3
test_pass_rate                 : 60.00%
avg_total_time                 : 2.34s
avg_debug_time                 : 1.12s

按 Bug 类型统计:
  null_pointer_dereference     : 1/1 (100.0%)
  buffer_overflow              : 1/1 (100.0%)
  memory_leak                  : 0/1 (0.0%)
  uninitialized_variable       : 1/1 (100.0%)
  off_by_one                   : 0/1 (0.0%)
  type_error                   : 0/1 (0.0%)
================================================================================
```

#### 2.2 完整评估（所有实例）

```bash
python scripts/evaluate_c_lang.py \
    --dataset c_lang_test_dataset.json \
    --work-dir ./c_eval_full \
    --c-standard c11 \
    --compiler gcc
```

#### 2.3 使用不同的 C 标准

```bash
# C99 标准
python scripts/evaluate_c_lang.py --dataset c_lang_test_dataset.json --c-standard c99

# C17 标准
python scripts/evaluate_c_lang.py --dataset c_lang_test_dataset.json --c-standard c17
```

#### 2.4 使用 Clang 编译器

```bash
python scripts/evaluate_c_lang.py --dataset c_lang_test_dataset.json --compiler clang
```

### 步骤 3：查看结果

评估完成后，结果将保存在 JSON 格式：

```bash
cat ./c_eval_test/results_20241214_120000.json
```

**结果文件结构：**
```json
{
  "evaluation_time": "2024-12-14T12:00:00",
  "language": "c",
  "config": {
    "c_standard": "c11",
    "compiler": "gcc",
    "total_instances": 6
  },
  "statistics": {
    "total_instances": 6,
    "debug_success_count": 5,
    "debug_success_rate": "83.33%",
    "compile_success_rate": "100.00%",
    "test_pass_rate": "66.67%",
    ...
  },
  "results": [
    {
      "instance_id": "c_null_ptr_001",
      "repo": "example_c_project",
      "bug_type": "null_pointer_dereference",
      "status": "success",
      "compile_status": "success",
      "debug_success": true,
      "test_passed": true,
      "debug_time": 0.45,
      "total_time": 1.23
    },
    ...
  ]
}
```

## 📊 创建自己的 C 语言数据集

### 方法 1：修改生成脚本

编辑 `scripts/generate_c_dataset.py`，添加新的测试用例：

```python
gen.add_instance(
    instance_id='c_my_bug_001',
    repo='my_project',
    problem_statement='我的 Bug 描述',
    bug_type='logic_error',
    buggy_code='''
    // 有 Bug 的代码
    ''',
    fixed_code='''
    // 修复后的代码
    ''',
    test_code='''
    // 测试代码
    '''
)
```

然后运行：
```bash
python scripts/generate_c_dataset.py
```

### 方法 2：从真实项目导入

```python
# import_c_project.py

import json
from pathlib import Path

def create_dataset_from_repo(repo_path: str, output_file: str):
    """从 Git 仓库导入测试用例"""
    
    instances = []
    
    # 遍历 Git 历史，找 Bug fixes
    # 这里需要与 Git 和项目特定的 Bug tracking 系统集成
    
    with open(output_file, 'w') as f:
        json.dump(instances, f, indent=2)

# 使用示例
# create_dataset_from_repo('/path/to/linux/kernel', 'linux_bugs.json')
```

### 方法 3：手动创建 JSON 文件

创建 `my_dataset.json`：

```json
[
  {
    "instance_id": "custom_bug_001",
    "repo": "my_project",
    "problem_statement": "函数未处理 NULL 参数",
    "bug_type": "null_pointer_dereference",
    "buggy_code": "void foo(int *p) { int x = *p; }",
    "fixed_code": "void foo(int *p) { if(p==NULL) return; int x = *p; }",
    "test_code": "int main() { foo(NULL); return 0; }"
  }
]
```

然后运行：
```bash
python scripts/evaluate_c_lang.py --dataset my_dataset.json
```

## 🔧 配置选项

### 命令行参数

```bash
python scripts/evaluate_c_lang.py --help

可选参数:
  --dataset DATASET          C 语言测试数据集文件（必需）
  --work-dir WORK_DIR        工作目录（默认: ./c_lang_evaluation）
  --max-instances N          最多评估 N 个实例（默认: 全部）
  --timeout SECONDS          单个实例超时时间（默认: 600 秒）
  --c-standard {c89,c99,c11,c17}  C 语言标准（默认: c11）
  --compiler {gcc,clang}     使用的编译器（默认: gcc）
```

### 环境变量配置

```bash
# 设置 Neo4j 连接
export NEO4J_URL=bolt://localhost:7687
export NEO4J_USER=neo4j
export NEO4J_PASSWORD=your_password

# 运行评估
python scripts/evaluate_c_lang.py --dataset c_lang_test_dataset.json
```

## 📈 性能分析示例

### 按 Bug 类型分析

```python
import json
import pandas as pd

with open('results.json', 'r') as f:
    data = json.load(f)

results_df = pd.DataFrame(data['results'])

# 按 Bug 类型统计
bug_stats = results_df.groupby('bug_type').agg({
    'test_passed': 'mean',
    'debug_time': 'mean'
})

print(bug_stats)
```

**输出：**
```
                                test_passed  debug_time
bug_type
buffer_overflow                        1.00        1.23
memory_leak                            0.67        2.45
null_pointer_dereference               1.00        0.89
type_error                             0.50        1.67
uninitialized_variable                 1.00        1.12
```

### 内存安全问题性能

```python
# 分析内存安全相关的 Bug 修复效果
memory_bugs = ['null_pointer_dereference', 'buffer_overflow', 'memory_leak', 'use_after_free']
memory_results = results_df[results_df['bug_type'].isin(memory_bugs)]

print(f"内存安全问题通过率: {memory_results['test_passed'].mean():.2%}")
print(f"平均调试时间: {memory_results['debug_time'].mean():.2f}s")
```

## 🔍 故障排除

### 问题 1：编译失败

**症状：** `compile_success_rate: 0%`

**解决方案：**
```bash
# 检查编译器是否安装
gcc --version

# 检查特定 C 标准的支持
gcc -std=c17 -c test.c

# 查看编译错误详情
python scripts/evaluate_c_lang.py --dataset dataset.json --max-instances 1
```

### 问题 2：超时

**症状：** `status: "timeout"`

**解决方案：**
```bash
# 增加超时时间
python scripts/evaluate_c_lang.py --dataset dataset.json --timeout 900

# 限制实例数进行调试
python scripts/evaluate_c_lang.py --dataset dataset.json --max-instances 2
```

### 问题 3：内存不足

**症状：** 程序崩溃或变慢

**解决方案：**
```bash
# 限制最大实例数
python scripts/evaluate_c_lang.py --dataset dataset.json --max-instances 10

# 使用流式处理（需要修改脚本）
```

## 📚 与 CodexGraph 集成

### 在 code_debugger.py 中使用 C 语言

```python
from modelscope_agent.agents.codexgraph_agent.task.code_debugger import CodexGraphAgentDebugger

# 初始化 C 语言调试器
debugger = CodexGraphAgentDebugger(
    llm=llm_instance,
    prompt_path='apps/codexgraph_agent/prompt',
    schema_path='apps/codexgraph_agent/config',
    task_id='c_debug_task',
    graph_db=graph_db_handler,
    language='c',  # 🔑 关键：指定为 C 语言
    max_iterations=5
)

# 调试 C 代码
result = debugger._run(
    user_query='修复这个 NULL 指针解引用的 Bug',
    file_path='main.c'
)
```

### 语言标签映射

C 语言使用特定的标签：

| Python | C |
|--------|---|
| CLASS | STRUCT |
| MODULE | FILE |
| FUNCTION | FUNCTION |
| FIELD | STRUCT_MEMBER |

## 🎯 性能基准

基于默认配置（GCC, C11）的预期性能：

| Bug 类型 | 通过率 | 平均时间 |
|---------|--------|---------|
| NULL Pointer | ~90% | ~1.0s |
| Buffer Overflow | ~70% | ~1.5s |
| Memory Leak | ~60% | ~2.0s |
| Off-by-One | ~80% | ~0.8s |
| 总体 | **~75%** | **~1.3s** |

## 📝 输出文件说明

评估完成后会生成以下文件：

```
c_lang_evaluation/
├── repos/                          # 所有测试项目的工作目录
│   ├── c_null_ptr_001/
│   │   ├── main.c                 # 源代码
│   │   ├── main.o                 # 编译的目标文件
│   │   ├── test.c                 # 测试代码
│   │   ├── test                   # 编译的测试程序
│   │   └── ...
│   └── ...
├── results_20241214_120000.json    # 最终评估结果
├── results_20241214_115000_intermediate.json  # 中间进度保存
└── c_lang_evaluation.log           # 详细日志
```

## 🚀 高级用法

### 并行化评估

```python
from concurrent.futures import ProcessPoolExecutor

def evaluate_in_parallel(dataset_file: str, num_workers: int = 4):
    """并行评估多个实例"""
    
    # 需要修改 evaluate_c_lang.py 支持并行处理
    # 这里仅为示例
    pass
```

### 与持续集成集成

```bash
# .github/workflows/c_eval.yml
name: C Language Evaluation

on: [push, pull_request]

jobs:
  evaluate:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v2
      - name: Generate C dataset
        run: python scripts/generate_c_dataset.py
      - name: Run evaluation
        run: python scripts/evaluate_c_lang.py --dataset c_lang_test_dataset.json
      - name: Upload results
        uses: actions/upload-artifact@v2
        with:
          name: c-eval-results
          path: c_lang_evaluation/
```

## 📖 更多信息

- [C 语言评估指南](../docs/C_LANG_EVALUATION_GUIDE.md)
- [SWE-Bench 评估指南](../docs/SWE_BENCH_EVALUATION_GUIDE.md)
- [CodexGraph 论文](https://arxiv.org/abs/2408.03910)

