# CodexGraph C 语言调试性能评估指南

> 针对 C 语言支持的 CodexGraph 改进版本，使用 Multi-SWE-Bench 数据集进行评估

## 📋 目录

1. [概述](#概述)
2. [C 语言数据集处理](#c-语言数据集处理)
3. [评估环境配置](#评估环境配置)
4. [C 语言特定评估指标](#c-语言特定评估指标)
5. [评估脚本](#评估脚本)
6. [结果分析](#结果分析)
7. [常见问题](#常见问题)

---

## 概述

### 改进点

CodexGraph 原版本主要支持 Python，改进版本扩展了对 C 语言的支持，包括：

- **语言检测**：自动识别代码语言（Python、C、C++）
- **C 语言图模型**：使用 C 特定的节点类型（STRUCT、FUNCTION、FILE 等）
- **代码解析**：支持 C 语言的 AST 解析和代码结构分析
- **符号表管理**：处理 C 语言的指针、内存操作等复杂特性

### 为什么选择 Multi-SWE-Bench

虽然 Multi-SWE-Bench 主要包含 Python 和 JavaScript 的问题，但：

1. **通用评估框架**：提供统一的评估指标和方法论
2. **可迁移性**：评估逻辑可应用于其他语言的数据集
3. **基准对标**：便于与其他系统的性能对比
4. **支持扩展**：可添加 C 语言特定的数据源

### 数据集补充方案

```
Multi-SWE-Bench (Python/JS)
    ↓
+ C 语言专用数据集 (可选)
    ├─ Linux Kernel Bug Database
    ├─ SQLite Bug Reports
    ├─ OpenSSL Security Issues
    ├─ GCC Bug Tracker
    └─ 自建 C 代码 Bug 数据集
```

---

## C 语言数据集处理

### 选项 1：使用 Python 数据集验证框架

虽然 SWE-bench 主要是 Python，但可用来验证调试框架的通用性：

```python
from datasets import load_dataset

# 加载数据集
dataset = load_dataset('princeton-nlp/SWE-bench_Lite', split='test')

# 过滤可能包含 C 代码的问题（示例）
c_related = [
    item for item in dataset 
    if any(keyword in item['problem_statement'].lower() 
           for keyword in ['c', 'c++', 'gcc', 'makefile', 'header', 'pointer', 'memory'])
]

print(f"找到 {len(c_related)} 个可能包含 C 代码的问题")
```

### 选项 2：创建 C 语言测试数据集

```python
# create_c_lang_dataset.py

import json
from pathlib import Path

class CLangTestDataset:
    """C 语言测试数据集"""
    
    def __init__(self):
        self.instances = []
    
    def add_instance(self, 
                    instance_id: str,
                    repo: str,
                    problem_statement: str,
                    buggy_code: str,
                    fixed_code: str,
                    test_code: str,
                    bug_type: str = 'generic'):
        """添加测试实例"""
        
        instance = {
            'instance_id': instance_id,
            'repo': repo,
            'problem_statement': problem_statement,
            'language': 'c',
            'buggy_code': buggy_code,
            'fixed_code': fixed_code,
            'test_code': test_code,
            'bug_type': bug_type,
            'patch': self._generate_patch(buggy_code, fixed_code),
            'FAIL_TO_PASS': [test_code],  # 应通过的测试
        }
        
        self.instances.append(instance)
    
    def _generate_patch(self, buggy: str, fixed: str) -> str:
        """生成补丁格式"""
        patch = f"--- a/buggy.c\n+++ b/fixed.c\n"
        
        # 简单的diff生成
        buggy_lines = buggy.split('\n')
        fixed_lines = fixed.split('\n')
        
        for i, (b, f) in enumerate(zip(buggy_lines, fixed_lines)):
            if b != f:
                patch += f"-{b}\n+{f}\n"
        
        return patch
    
    def save_to_json(self, output_file: str):
        """保存为 JSON 格式"""
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(self.instances, f, indent=2, ensure_ascii=False)
        
        print(f"✅ 已保存 {len(self.instances)} 个 C 语言测试实例到 {output_file}")

# 使用示例
dataset = CLangTestDataset()

# 添加示例：空指针解引用
dataset.add_instance(
    instance_id='c_lang__null_ptr_001',
    repo='example/c_project',
    problem_statement='函数在处理 NULL 指针时未进行检查，导致段错误',
    buggy_code='''
void process_data(int *ptr) {
    // 没有检查 ptr 是否为 NULL
    int value = *ptr;  // 可能的 NULL 解引用
    printf("Value: %d\\n", value);
}
''',
    fixed_code='''
void process_data(int *ptr) {
    // 添加 NULL 检查
    if (ptr == NULL) {
        printf("Error: NULL pointer\\n");
        return;
    }
    int value = *ptr;
    printf("Value: %d\\n", value);
}
''',
    test_code='''
void test_null_ptr() {
    // 应该安全处理 NULL
    process_data(NULL);
    
    // 应该正常处理有效指针
    int x = 42;
    process_data(&x);
}
''',
    bug_type='null_pointer_dereference'
)

# 添加示例：缓冲区溢出
dataset.add_instance(
    instance_id='c_lang__buffer_overflow_001',
    repo='example/c_project',
    problem_statement='字符串复制函数未检查缓冲区大小，可能导致缓冲区溢出',
    buggy_code='''
void copy_string(char *dest, const char *src) {
    // 危险：未检查源字符串长度
    strcpy(dest, src);  // 缓冲区溢出风险
}
''',
    fixed_code='''
void copy_string(char *dest, const char *src, size_t dest_size) {
    // 安全：使用 strncpy 限制复制长度
    strncpy(dest, src, dest_size - 1);
    dest[dest_size - 1] = '\\0';  // 确保空终止
}
''',
    test_code='''
void test_buffer_copy() {
    char buffer[32];
    copy_string(buffer, "Hello, World!", sizeof(buffer));
    assert(strlen(buffer) < sizeof(buffer));
}
''',
    bug_type='buffer_overflow'
)

dataset.save_to_json('c_lang_test_dataset.json')
```

### 选项 3：从现有 C 项目收集数据

```python
# collect_c_bugs_from_repos.py

import os
import json
from pathlib import Path
import subprocess

class CProjectBugCollector:
    """从开源 C 项目收集 Bug 数据"""
    
    REPOSITORIES = [
        # 这些是真实的开源 C 项目
        {
            'name': 'linux',
            'url': 'https://github.com/torvalds/linux.git',
            'commit_range': 'HEAD~100..HEAD'
        },
        {
            'name': 'sqlite',
            'url': 'https://github.com/sqlite/sqlite.git',
            'commit_range': 'HEAD~50..HEAD'
        },
        {
            'name': 'openssl',
            'url': 'https://github.com/openssl/openssl.git',
            'commit_range': 'HEAD~30..HEAD'
        },
    ]
    
    def __init__(self, work_dir: str = './c_projects'):
        self.work_dir = Path(work_dir)
        self.work_dir.mkdir(exist_ok=True)
    
    def collect_from_repo(self, repo_info: dict) -> list:
        """从单个仓库收集 Bug 数据"""
        
        repo_path = self.work_dir / repo_info['name']
        instances = []
        
        # 克隆或更新仓库
        if repo_path.exists():
            subprocess.run(['git', 'pull'], cwd=repo_path)
        else:
            subprocess.run(['git', 'clone', repo_info['url'], str(repo_path)])
        
        # 获取提交历史
        os.chdir(repo_path)
        result = subprocess.run(
            ['git', 'log', '--pretty=format:%H|%s', repo_info['commit_range']],
            capture_output=True,
            text=True
        )
        
        commits = result.stdout.strip().split('\n')
        
        for commit_line in commits[:10]:  # 取最近 10 个 commit
            try:
                commit_hash, message = commit_line.split('|', 1)
                
                # 检查是否是 bug fix
                if any(keyword in message.lower() 
                       for keyword in ['fix', 'bug', 'error', 'crash', 'memory']):
                    
                    # 获取这个提交的详细信息
                    diff_result = subprocess.run(
                        ['git', 'show', commit_hash],
                        capture_output=True,
                        text=True
                    )
                    
                    instance = {
                        'instance_id': f"{repo_info['name']}_{commit_hash[:8]}",
                        'repo': repo_info['name'],
                        'problem_statement': message,
                        'language': 'c',
                        'commit': commit_hash,
                        'patch': diff_result.stdout,
                    }
                    
                    instances.append(instance)
            
            except Exception as e:
                print(f"处理 commit 失败: {e}")
        
        return instances

# 使用示例
# collector = CProjectBugCollector()
# for repo in collector.REPOSITORIES:
#     instances = collector.collect_from_repo(repo)
#     print(f"从 {repo['name']} 收集了 {len(instances)} 个实例")
```

---

## 评估环境配置

### 步骤 1：配置 C 语言支持

修改 CodexGraph 的初始化代码，确保支持 C 语言：

```python
# evaluate_c_lang.py

from modelscope_agent.agents.codexgraph_agent.task.code_debugger import CodexGraphAgentDebugger
from modelscope_agent.environment.graph_database import GraphDatabaseHandler

def init_c_debugger(neo4j_config: dict) -> CodexGraphAgentDebugger:
    """初始化 C 语言调试器"""
    
    from modelscope_agent.llm.base import LLMBase
    
    # 初始化 LLM
    llm = LLMBase(model_name='qwen-max')
    
    # 初始化图数据库处理器
    graph_db = GraphDatabaseHandler(
        url=neo4j_config['url'],
        user=neo4j_config['user'],
        password=neo4j_config['password']
    )
    
    # 初始化 C 语言调试器（关键：设置 language='c'）
    debugger = CodexGraphAgentDebugger(
        llm=llm,
        prompt_path='apps/codexgraph_agent/prompt',
        schema_path='apps/codexgraph_agent/config',
        task_id='swe_bench_c_evaluation',
        graph_db=graph_db,
        max_iterations=5,
        max_iterations_cypher=5,
        language='c',  # 🔑 关键参数：指定为 C 语言
        message_callback=None
    )
    
    return debugger

# 配置
neo4j_config = {
    'url': 'bolt://localhost:7687',
    'user': 'neo4j',
    'password': 'your_password'
}

debugger = init_c_debugger(neo4j_config)
print("✅ C 语言调试器初始化完成")
```

### 步骤 2：配置 C 语言代码解析

```python
# c_code_parser.py

from enum import Enum
import re

class CNodeType(Enum):
    """C 语言节点类型"""
    FILE = 'FILE'
    STRUCT = 'STRUCT'
    UNION = 'UNION'
    FUNCTION = 'FUNCTION'
    FUNCTION_PARAM = 'FUNCTION_PARAM'
    VARIABLE = 'VARIABLE'
    MACRO = 'MACRO'
    TYPEDEF = 'TYPEDEF'
    INCLUDE = 'INCLUDE'

class CLangCodeParser:
    """C 语言代码解析器"""
    
    def parse_function(self, code: str) -> list:
        """解析函数定义"""
        # 函数签名正则表达式
        pattern = r'(\w+\s*\*?\s+(\w+)\s*\([^)]*\))\s*\{'
        matches = re.finditer(pattern, code)
        
        functions = []
        for match in matches:
            functions.append({
                'type': CNodeType.FUNCTION.value,
                'signature': match.group(1),
                'name': match.group(2),
                'line': code[:match.start()].count('\n') + 1
            })
        
        return functions
    
    def parse_struct(self, code: str) -> list:
        """解析结构体定义"""
        pattern = r'struct\s+(\w+)\s*\{'
        matches = re.finditer(pattern, code)
        
        structs = []
        for match in matches:
            structs.append({
                'type': CNodeType.STRUCT.value,
                'name': match.group(1),
                'line': code[:match.start()].count('\n') + 1
            })
        
        return structs
    
    def parse_all(self, code: str) -> dict:
        """解析所有 C 语言元素"""
        
        return {
            'functions': self.parse_function(code),
            'structs': self.parse_struct(code),
            'macros': self.parse_macros(code),
            'includes': self.parse_includes(code),
        }
    
    def parse_macros(self, code: str) -> list:
        """解析宏定义"""
        pattern = r'#define\s+(\w+)'
        matches = re.finditer(pattern, code)
        
        return [
            {
                'type': CNodeType.MACRO.value,
                'name': match.group(1),
                'line': code[:match.start()].count('\n') + 1
            }
            for match in matches
        ]
    
    def parse_includes(self, code: str) -> list:
        """解析包含指令"""
        pattern = r'#include\s+[<"](.+?)[>"]'
        matches = re.finditer(pattern, code)
        
        return [
            {
                'type': CNodeType.INCLUDE.value,
                'file': match.group(1),
                'line': code[:match.start()].count('\n') + 1
            }
            for match in matches
        ]
```

### 步骤 3：构建 C 代码图数据库

```python
# build_c_graph_db.py

from neo4j import GraphDatabase

class CLangGraphBuilder:
    """C 语言代码图数据库构建器"""
    
    def __init__(self, neo4j_uri: str, user: str, password: str):
        self.driver = GraphDatabase.driver(neo4j_uri, auth=(user, password))
    
    def create_function_node(self, session, function: dict, file_path: str):
        """创建函数节点"""
        
        query = """
        CREATE (f:FUNCTION {
            name: $name,
            signature: $signature,
            file_path: $file_path,
            line: $line,
            language: 'c'
        })
        """
        
        session.run(query, 
                   name=function['name'],
                   signature=function['signature'],
                   file_path=file_path,
                   line=function['line'])
    
    def create_struct_node(self, session, struct: dict, file_path: str):
        """创建结构体节点"""
        
        query = """
        CREATE (s:STRUCT {
            name: $name,
            file_path: $file_path,
            line: $line,
            language: 'c'
        })
        """
        
        session.run(query,
                   name=struct['name'],
                   file_path=file_path,
                   line=struct['line'])
    
    def build_from_repo(self, repo_path: str, db_name: str = 'c_project'):
        """从 C 仓库构建图数据库"""
        
        from pathlib import Path
        
        parser = CLangCodeParser()
        
        with self.driver.session(database=db_name) as session:
            # 遍历所有 .c 和 .h 文件
            for c_file in Path(repo_path).rglob('*.c'):
                with open(c_file, 'r', errors='ignore') as f:
                    code = f.read()
                
                parsed = parser.parse_all(code)
                
                # 创建节点
                for func in parsed['functions']:
                    self.create_function_node(session, func, str(c_file))
                
                for struct in parsed['structs']:
                    self.create_struct_node(session, struct, str(c_file))
```

---

## C 语言特定评估指标

### 扩展评估指标

```python
# c_lang_metrics.py

from dataclasses import dataclass
from enum import Enum

class CBugType(Enum):
    """C 语言 Bug 类型"""
    NULL_POINTER = "null_pointer_dereference"
    BUFFER_OVERFLOW = "buffer_overflow"
    USE_AFTER_FREE = "use_after_free"
    MEMORY_LEAK = "memory_leak"
    UNINITIALIZED_VAR = "uninitialized_variable"
    OFF_BY_ONE = "off_by_one"
    TYPE_ERROR = "type_error"
    RACE_CONDITION = "race_condition"
    LOGIC_ERROR = "logic_error"

@dataclass
class CLangEvaluationMetrics:
    """C 语言评估指标"""
    
    instance_id: str
    repo: str
    language: str = 'c'
    
    # 基础指标
    debug_success: bool = False
    test_passed: bool = False
    debug_time: float = 0.0
    
    # C 语言特定指标
    bug_type: CBugType = None
    memory_safety_correct: float = 0.0  # 0-1，是否正确处理内存安全问题
    null_check_added: bool = False      # 是否添加了 NULL 检查
    bounds_check_added: bool = False    # 是否添加了边界检查
    
    # 代码质量
    plan_quality: float = 0.0
    c_idiom_correctness: float = 0.0    # C 习惯用法的正确性
    patch_relevance: float = 0.0

class CLangMetricsEvaluator:
    """C 语言指标评估器"""
    
    def evaluate_memory_safety(self, 
                              bug_type: CBugType,
                              predicted_fix: str) -> float:
        """评估内存安全性修复的正确性"""
        
        score = 0.0
        
        # 检查 NULL 指针检查
        if bug_type == CBugType.NULL_POINTER:
            if 'NULL' in predicted_fix and 'if' in predicted_fix:
                score += 0.5
        
        # 检查缓冲区检查
        if bug_type == CBugType.BUFFER_OVERFLOW:
            if any(check in predicted_fix for check in ['sizeof', 'strlen', 'strncpy']):
                score += 0.5
        
        # 检查内存释放
        if bug_type == CBugType.USE_AFTER_FREE:
            if 'free' in predicted_fix or 'NULL' in predicted_fix:
                score += 0.5
        
        return min(score, 1.0)
    
    def evaluate_c_idioms(self, code: str) -> float:
        """评估 C 习惯用法的使用"""
        
        score = 0.0
        
        # 检查常见的 C 习惯
        checks = [
            ('sizeof', 0.1),
            ('assert', 0.1),
            ('return', 0.1),
            ('static', 0.1),
            ('const', 0.1),
            ('restrict', 0.1),
        ]
        
        for keyword, points in checks:
            if keyword in code:
                score += points
        
        return min(score, 1.0)
```

---

## 评估脚本

### C 语言评估脚本

```python
# evaluate_codexgraph_c_lang.py

import json
import logging
from typing import Dict, List
from pathlib import Path
import subprocess
import time

logger = logging.getLogger(__name__)

class CLangSWEBenchEvaluator:
    """C 语言 SWE-Bench 评估器"""
    
    def __init__(self, 
                 dataset_file: str,
                 work_dir: str = './c_lang_evaluation',
                 neo4j_config: dict = None):
        
        self.dataset_file = dataset_file
        self.work_dir = Path(work_dir)
        self.work_dir.mkdir(parents=True, exist_ok=True)
        self.neo4j_config = neo4j_config or {
            'url': 'bolt://localhost:7687',
            'user': 'neo4j',
            'password': 'password'
        }
        
        self.results = []
    
    def load_dataset(self) -> List[Dict]:
        """加载 C 语言测试数据集"""
        
        with open(self.dataset_file, 'r') as f:
            dataset = json.load(f)
        
        print(f"✅ 加载了 {len(dataset)} 个 C 语言测试用例")
        return dataset
    
    def setup_c_project(self, instance: Dict) -> str:
        """设置 C 项目工作目录"""
        
        project_dir = self.work_dir / instance['instance_id']
        project_dir.mkdir(parents=True, exist_ok=True)
        
        # 创建 C 源文件
        c_file = project_dir / 'main.c'
        with open(c_file, 'w') as f:
            f.write(instance['buggy_code'])
        
        # 创建测试文件
        test_file = project_dir / 'test.c'
        with open(test_file, 'w') as f:
            f.write(instance['test_code'])
        
        return str(project_dir)
    
    def compile_c_code(self, project_dir: str) -> bool:
        """编译 C 代码"""
        
        try:
            result = subprocess.run(
                ['gcc', '-c', f'{project_dir}/main.c', '-o', f'{project_dir}/main.o'],
                capture_output=True,
                text=True,
                timeout=30
            )
            
            return result.returncode == 0
        
        except Exception as e:
            logger.error(f"编译失败: {e}")
            return False
    
    def run_tests(self, project_dir: str) -> Dict:
        """运行测试"""
        
        try:
            # 编译测试
            subprocess.run(
                ['gcc', f'{project_dir}/test.c', f'{project_dir}/main.o', 
                 '-o', f'{project_dir}/test'],
                capture_output=True,
                timeout=30
            )
            
            # 执行测试
            result = subprocess.run(
                [f'{project_dir}/test'],
                capture_output=True,
                text=True,
                timeout=10
            )
            
            return {
                'passed': result.returncode == 0,
                'output': result.stdout,
                'error': result.stderr
            }
        
        except Exception as e:
            return {'passed': False, 'error': str(e)}
    
    def evaluate_instance(self, instance: Dict) -> Dict:
        """评估单个测试实例"""
        
        logger.info(f"评估: {instance['instance_id']}")
        
        start_time = time.time()
        result = {
            'instance_id': instance['instance_id'],
            'repo': instance['repo'],
            'bug_type': instance.get('bug_type', 'generic'),
            'status': 'pending',
            'debug_time': 0,
            'compile_passed': False,
            'test_passed': False,
        }
        
        try:
            # 1. 设置项目
            project_dir = self.setup_c_project(instance)
            
            # 2. 尝试编译原始代码（应该失败或有警告）
            compile_ok = self.compile_c_code(project_dir)
            
            # 3. 这里应该调用 CodexGraph 调试器
            # debug_result = self.debug_with_codexgraph(instance)
            
            # 4. 运行测试
            test_result = self.run_tests(project_dir)
            result['test_passed'] = test_result['passed']
            
            result['status'] = 'success'
            result['debug_time'] = time.time() - start_time
            
        except Exception as e:
            logger.error(f"评估失败: {e}")
            result['status'] = 'failed'
            result['error'] = str(e)
            result['debug_time'] = time.time() - start_time
        
        return result
    
    def evaluate_all(self, limit: int = None) -> List[Dict]:
        """评估所有实例"""
        
        dataset = self.load_dataset()
        
        if limit:
            dataset = dataset[:limit]
        
        for i, instance in enumerate(dataset):
            logger.info(f"[{i+1}/{len(dataset)}]")
            result = self.evaluate_instance(instance)
            self.results.append(result)
        
        return self.results
    
    def save_results(self, output_file: str = None):
        """保存评估结果"""
        
        if output_file is None:
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            output_file = self.work_dir / f'results_{timestamp}.json'
        
        output = {
            'timestamp': datetime.now().isoformat(),
            'language': 'c',
            'total_instances': len(self.results),
            'test_pass_rate': sum(1 for r in self.results if r['test_passed']) / len(self.results),
            'results': self.results
        }
        
        with open(output_file, 'w') as f:
            json.dump(output, f, indent=2)
        
        logger.info(f"结果已保存至: {output_file}")

# 使用示例
if __name__ == '__main__':
    evaluator = CLangSWEBenchEvaluator(
        dataset_file='c_lang_test_dataset.json',
        work_dir='./c_lang_eval'
    )
    
    evaluator.evaluate_all(limit=10)
    evaluator.save_results()
```

---

## 结果分析

### C 语言特定的分析

```python
# analyze_c_lang_results.py

import json
import pandas as pd
from collections import defaultdict

def analyze_c_lang_results(results_file: str):
    """分析 C 语言评估结果"""
    
    with open(results_file, 'r') as f:
        data = json.load(f)
    
    results = pd.DataFrame(data['results'])
    
    # 按 Bug 类型统计
    print("\n📊 按 Bug 类型的性能:")
    print("-" * 70)
    
    bug_stats = results.groupby('bug_type').agg({
        'test_passed': 'mean',
        'debug_time': 'mean'
    }).round(3)
    
    bug_stats.columns = ['Pass Rate', 'Avg Time (s)']
    print(bug_stats)
    
    # 内存安全问题统计
    memory_bugs = ['null_pointer_dereference', 'buffer_overflow', 'use_after_free', 'memory_leak']
    memory_results = results[results['bug_type'].isin(memory_bugs)]
    
    print(f"\n💾 内存安全问题性能:")
    print(f"  总数: {len(memory_results)}")
    print(f"  通过率: {memory_results['test_passed'].mean():.2%}")
    print(f"  平均调试时间: {memory_results['debug_time'].mean():.2f}s")
    
    # 与 Python 性能对比
    print(f"\n🔄 C vs Python 性能对比:")
    print(f"  C 语言通过率: {results['test_passed'].mean():.2%}")
    print(f"  （需要与 Python 数据集结果对比）")
```

---

## 常见问题

### Q1: 如何处理 C 语言编译错误？

```python
def handle_c_compile_error(error_output: str) -> str:
    """处理编译错误信息"""
    
    # 提取关键错误信息
    lines = error_output.split('\n')
    errors = [line for line in lines if 'error:' in line.lower()]
    
    # 返回摘要
    return '\n'.join(errors[:3])  # 返回前 3 个错误
```

### Q2: 支持多个 C 标准吗？

```python
SUPPORTED_C_STANDARDS = {
    'c89': '-std=c89',
    'c99': '-std=c99',
    'c11': '-std=c11',
    'c17': '-std=c17',
}

def compile_with_standard(c_file: str, standard: str = 'c11') -> bool:
    """使用特定 C 标准编译"""
    
    flag = SUPPORTED_C_STANDARDS.get(standard, '-std=c11')
    
    result = subprocess.run(
        ['gcc', flag, '-c', c_file],
        capture_output=True
    )
    
    return result.returncode == 0
```

### Q3: 如何处理编译器警告？

```python
def extract_warnings(output: str) -> List[str]:
    """提取编译器警告"""
    
    warnings = [line for line in output.split('\n') 
                if 'warning:' in line.lower()]
    
    return warnings

# 根据警告级别决定是否继续
CRITICAL_WARNINGS = ['uninitialized', 'implicit-function-declaration']

def has_critical_warnings(warnings: List[str]) -> bool:
    """检查是否有严重警告"""
    
    return any(critical in warning.lower() 
              for warning in warnings 
              for critical in CRITICAL_WARNINGS)
```

### Q4: 如何处理内存地址空间布局随机化（ASLR）对测试的影响？

```python
import os

def disable_aslr_for_testing():
    """禁用 ASLR（仅在 Linux 上）"""
    
    try:
        # 查看当前 ASLR 状态
        with open('/proc/sys/kernel/randomize_va_space', 'r') as f:
            print(f"Current ASLR setting: {f.read()}")
        
        # 禁用 ASLR（需要 root 权限）
        os.system('echo 0 | sudo tee /proc/sys/kernel/randomize_va_space')
    
    except Exception as e:
        print(f"Warning: Cannot disable ASLR: {e}")
```

---

## 推荐评估步骤

### 阶段 1: 框架验证（1-2 天）

```bash
# 使用小的测试数据集验证框架
python evaluate_codexgraph_c_lang.py \
    --dataset c_lang_test_dataset.json \
    --limit 5 \
    --work-dir ./test_eval
```

### 阶段 2: 中等规模评估（2-3 天）

```bash
# 使用更多的 C 语言问题
python evaluate_codexgraph_c_lang.py \
    --dataset c_lang_test_dataset.json \
    --limit 50 \
    --work-dir ./medium_eval
```

### 阶段 3: 完整评估（3-5 天）

```bash
# 评估全部 C 语言数据集
python evaluate_codexgraph_c_lang.py \
    --dataset c_lang_test_dataset.json \
    --work-dir ./full_eval
```

---

## 总结

| 方面 | Python | C 语言 |
|------|--------|--------|
| **数据来源** | SWE-bench Lite | 自建 + 真实项目 |
| **评估指标** | 通用指标 | + 内存安全指标 |
| **节点类型** | CLASS, FUNCTION | STRUCT, FUNCTION, FILE |
| **典型 Bug** | 逻辑错误 | 内存安全、指针错误 |
| **编译环节** | 无 | 需要编译验证 |

---

## 参考资源

- **C 语言 Bug 数据集**：CWE Top 25（https://cwe.mitre.org/top25/）
- **开源 C 项目**：Linux Kernel, SQLite, OpenSSL
- **编译器工具**：GCC, Clang
- **静态分析工具**：Clang Static Analyzer, Coverity

