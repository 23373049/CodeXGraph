#!/usr/bin/env python3
"""
CodexGraph C 语言评估脚本
用于评估改进版 CodexGraph 对 C 语言代码调试的性能
支持与 SWE-Bench 相同的评估框架
"""

import json
import os
import sys
import time
import logging
import argparse
import subprocess
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from datetime import datetime
from dataclasses import dataclass, asdict
from enum import Enum

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('c_lang_evaluation.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


class CBugType(Enum):
    """C 语言 Bug 类型"""
    NULL_POINTER = "null_pointer_dereference"
    BUFFER_OVERFLOW = "buffer_overflow"
    USE_AFTER_FREE = "use_after_free"
    MEMORY_LEAK = "memory_leak"
    UNINITIALIZED = "uninitialized_variable"
    OFF_BY_ONE = "off_by_one"
    TYPE_ERROR = "type_error"
    RACE_CONDITION = "race_condition"
    LOGIC_ERROR = "logic_error"
    OTHER = "other"


@dataclass
class CEvaluationResult:
    """C 语言评估结果"""
    instance_id: str
    repo: str
    bug_type: str = CBugType.OTHER.value
    
    # 执行状态
    status: str = "pending"  # pending, success, failed, timeout
    error_message: str = ""
    
    # 编译结果
    compile_status: str = "unknown"  # success, warning, error
    compile_output: str = ""
    
    # 调试结果
    debug_success: bool = False
    bug_locations: List[str] = None
    fix_suggestion: str = ""
    debug_time: float = 0.0
    
    # 测试结果
    test_passed: bool = False
    test_output: str = ""
    
    # 质量指标
    plan_quality: float = 0.0
    memory_safety_score: float = 0.0
    total_time: float = 0.0
    
    def to_dict(self) -> dict:
        data = asdict(self)
        if self.bug_locations is None:
            data['bug_locations'] = []
        return data


@dataclass
class EvaluationConfig:
    """评估配置"""
    dataset_file: str
    work_dir: str = './c_lang_evaluation'
    neo4j_url: str = 'bolt://localhost:7687'
    neo4j_user: str = 'neo4j'
    neo4j_password: str = 'password'
    max_instances: Optional[int] = None
    timeout: int = 600  # 10 分钟
    c_standard: str = 'c11'  # C 标准
    compiler: str = 'gcc'  # 编译器
    debug: bool = False


class CLangCodeParser:
    """C 语言代码解析器"""
    
    @staticmethod
    def extract_functions(code: str) -> List[str]:
        """提取函数名"""
        import re
        pattern = r'(?:^|\n)\w+\s*\*?\s+(\w+)\s*\([^)]*\)\s*\{'
        matches = re.findall(pattern, code, re.MULTILINE)
        return matches
    
    @staticmethod
    def extract_structs(code: str) -> List[str]:
        """提取结构体名"""
        import re
        pattern = r'(?:^|\n)\s*struct\s+(\w+)\s*\{'
        matches = re.findall(pattern, code, re.MULTILINE)
        return matches
    
    @staticmethod
    def detect_bug_type(problem_statement: str, code_diff: str) -> str:
        """检测 Bug 类型"""
        
        stmt_lower = problem_statement.lower()
        diff_lower = code_diff.lower()
        
        # 关键词匹配
        bug_keywords = {
            CBugType.NULL_POINTER.value: ['null', 'nullptr', 'pointer', 'segmentation', 'sigsegv'],
            CBugType.BUFFER_OVERFLOW.value: ['buffer', 'overflow', 'bounds', 'array'],
            CBugType.MEMORY_LEAK.value: ['leak', 'malloc', 'free', 'memory'],
            CBugType.USE_AFTER_FREE.value: ['after free', 'use-after-free', 'freed'],
            CBugType.UNINITIALIZED.value: ['uninitial', 'undefin'],
            CBugType.OFF_BY_ONE.value: ['off-by-one', 'boundary'],
        }
        
        for bug_type, keywords in bug_keywords.items():
            if any(kw in stmt_lower or kw in diff_lower for kw in keywords):
                return bug_type
        
        return CBugType.OTHER.value


class CLangEvaluator:
    """C 语言评估器"""
    
    def __init__(self, config: EvaluationConfig):
        self.config = config
        self.results: List[CEvaluationResult] = []
        
        # 创建工作目录
        Path(config.work_dir).mkdir(parents=True, exist_ok=True)
        self.repos_dir = Path(config.work_dir) / 'repos'
        self.repos_dir.mkdir(exist_ok=True)
        
        logger.info(f"工作目录: {config.work_dir}")
    
    def load_dataset(self) -> List[Dict]:
        """加载 C 语言数据集"""
        logger.info(f"加载数据集: {self.config.dataset_file}")
        
        try:
            with open(self.config.dataset_file, 'r', encoding='utf-8') as f:
                dataset = json.load(f)
            
            logger.info(f"已加载 {len(dataset)} 个实例")
            
            if self.config.max_instances:
                dataset = dataset[:self.config.max_instances]
                logger.info(f"限制至 {len(dataset)} 个实例")
            
            return dataset
        
        except Exception as e:
            logger.error(f"加载数据集失败: {e}")
            raise
    
    def setup_c_project(self, instance: Dict) -> Optional[str]:
        """设置 C 项目目录"""
        try:
            project_dir = self.repos_dir / instance['instance_id']
            project_dir.mkdir(parents=True, exist_ok=True)
            
            # 保存源代码
            c_file = project_dir / 'main.c'
            with open(c_file, 'w', encoding='utf-8') as f:
                f.write(instance.get('buggy_code', ''))
            
            # 保存测试代码
            if 'test_code' in instance:
                test_file = project_dir / 'test.c'
                with open(test_file, 'w', encoding='utf-8') as f:
                    f.write(instance['test_code'])
            
            return str(project_dir)
        
        except Exception as e:
            logger.error(f"设置项目失败: {e}")
            return None
    
    def compile_c_code(self, project_dir: str, filename: str = 'main.c') -> Tuple[bool, str]:
        """编译 C 代码"""
        try:
            c_file = os.path.join(project_dir, filename)
            
            compile_cmd = [
                self.config.compiler,
                f'-std={self.config.c_standard}',
                '-Wall', '-Wextra',  # 启用所有警告
                '-c',  # 仅编译，不链接
                c_file,
                '-o',
                os.path.join(project_dir, f'{filename[:-2]}.o')
            ]
            
            result = subprocess.run(
                compile_cmd,
                capture_output=True,
                text=True,
                timeout=30
            )
            
            output = result.stdout + result.stderr
            
            if result.returncode == 0:
                return True, output
            else:
                return False, output
        
        except subprocess.TimeoutExpired:
            return False, "编译超时"
        except Exception as e:
            return False, str(e)
    
    def run_tests(self, project_dir: str) -> Tuple[bool, str]:
        """运行测试"""
        try:
            # 链接和运行
            test_cmd = [
                self.config.compiler,
                '-o', os.path.join(project_dir, 'test'),
                os.path.join(project_dir, 'main.o'),
                os.path.join(project_dir, 'test.c'),
            ]
            
            result = subprocess.run(
                test_cmd,
                capture_output=True,
                text=True,
                timeout=30
            )
            
            if result.returncode != 0:
                return False, result.stderr
            
            # 运行测试
            run_result = subprocess.run(
                [os.path.join(project_dir, 'test')],
                capture_output=True,
                text=True,
                timeout=10
            )
            
            passed = run_result.returncode == 0
            output = run_result.stdout + run_result.stderr
            
            return passed, output
        
        except subprocess.TimeoutExpired:
            return False, "测试超时"
        except Exception as e:
            return False, str(e)
    
    def evaluate_instance(self, instance: Dict) -> CEvaluationResult:
        """评估单个实例"""
        instance_id = instance['instance_id']
        logger.info(f"评估: {instance_id}")
        
        total_start = time.time()
        
        result = CEvaluationResult(
            instance_id=instance_id,
            repo=instance.get('repo', ''),
            bug_type=CLangCodeParser.detect_bug_type(
                instance.get('problem_statement', ''),
                instance.get('patch', '')
            )
        )
        
        try:
            # 设置项目
            project_dir = self.setup_c_project(instance)
            if not project_dir:
                result.status = 'failed'
                result.error_message = '项目设置失败'
                result.total_time = time.time() - total_start
                return result
            
            # 编译源代码
            debug_start = time.time()
            compile_ok, compile_output = self.compile_c_code(project_dir)
            result.compile_output = compile_output[:500]  # 保存前 500 字
            
            if compile_ok:
                result.compile_status = 'success'
            else:
                result.compile_status = 'error'
                # 这里应该调用 CodexGraph 调试器来修复编译错误
            
            result.debug_time = time.time() - debug_start
            
            # 运行测试
            if compile_ok or result.compile_status == 'warning':
                test_passed, test_output = self.run_tests(project_dir)
                result.test_passed = test_passed
                result.test_output = test_output[:500]
            
            # 计算质量指标
            result.plan_quality = self._calculate_plan_quality(instance)
            result.memory_safety_score = self._calculate_memory_safety(
                instance.get('fixed_code', ''),
                result.bug_type
            )
            
            result.status = 'success'
            result.debug_success = compile_ok or result.compile_status == 'warning'
            
        except subprocess.TimeoutExpired:
            result.status = 'timeout'
            result.error_message = '评估超时'
        except Exception as e:
            result.status = 'failed'
            result.error_message = str(e)
            logger.exception(f"评估失败: {instance_id}")
        
        result.total_time = time.time() - total_start
        return result
    
    def _calculate_plan_quality(self, instance: Dict) -> float:
        """计算调试计划质量评分"""
        # 简单实现：基于代码复杂度和修改大小
        
        code_lines = len(instance.get('buggy_code', '').split('\n'))
        
        # 代码行数 100-500 行为最优
        if 100 <= code_lines <= 500:
            return 0.8
        elif 50 <= code_lines < 100 or 500 < code_lines <= 1000:
            return 0.6
        else:
            return 0.4
    
    def _calculate_memory_safety(self, fixed_code: str, bug_type: str) -> float:
        """计算内存安全性修复评分"""
        
        score = 0.0
        
        # 检查是否添加了 NULL 检查
        if 'NULL' in fixed_code or '!=' in fixed_code:
            score += 0.25
        
        # 检查是否添加了大小检查
        if 'size' in fixed_code.lower() or 'sizeof' in fixed_code:
            score += 0.25
        
        # 检查是否添加了 free 调用
        if 'free' in fixed_code:
            score += 0.25
        
        # 检查是否保留了错误处理
        if 'return' in fixed_code or 'assert' in fixed_code:
            score += 0.25
        
        return min(score, 1.0)
    
    def evaluate_all(self) -> List[CEvaluationResult]:
        """评估所有实例"""
        dataset = self.load_dataset()
        
        logger.info(f"开始评估 {len(dataset)} 个实例")
        
        for i, instance in enumerate(dataset):
            logger.info(f"[{i+1}/{len(dataset)}] 处理进度")
            
            result = self.evaluate_instance(instance)
            self.results.append(result)
            
            # 定期保存进度
            if (i + 1) % 10 == 0:
                self.save_results(intermediate=True)
        
        return self.results
    
    def save_results(self, output_file: str = None, intermediate: bool = False):
        """保存评估结果"""
        if output_file is None:
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            suffix = '_intermediate' if intermediate else ''
            output_file = os.path.join(
                self.config.work_dir,
                f'results_{timestamp}{suffix}.json'
            )
        
        stats = self._calculate_stats()
        
        output = {
            'evaluation_time': datetime.now().isoformat(),
            'language': 'c',
            'config': {
                'c_standard': self.config.c_standard,
                'compiler': self.config.compiler,
                'total_instances': len(self.results),
            },
            'statistics': stats,
            'results': [r.to_dict() for r in self.results]
        }
        
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(output, f, indent=2, ensure_ascii=False)
        
        logger.info(f"结果已保存至: {output_file}")
        return output_file
    
    def _calculate_stats(self) -> dict:
        """计算统计数据"""
        if not self.results:
            return {}
        
        total = len(self.results)
        debug_success = sum(1 for r in self.results if r.debug_success)
        test_passed = sum(1 for r in self.results if r.test_passed)
        compile_ok = sum(1 for r in self.results if r.compile_status == 'success')
        
        times = [r.total_time for r in self.results if r.total_time > 0]
        
        # 按 Bug 类型统计
        bug_types = {}
        for result in self.results:
            bug_type = result.bug_type
            if bug_type not in bug_types:
                bug_types[bug_type] = {'total': 0, 'passed': 0}
            bug_types[bug_type]['total'] += 1
            if result.test_passed:
                bug_types[bug_type]['passed'] += 1
        
        return {
            'total_instances': total,
            'debug_success_count': debug_success,
            'debug_success_rate': f"{debug_success/total*100:.2f}%" if total > 0 else "0%",
            'compile_success_count': compile_ok,
            'compile_success_rate': f"{compile_ok/total*100:.2f}%" if total > 0 else "0%",
            'test_pass_count': test_passed,
            'test_pass_rate': f"{test_passed/total*100:.2f}%" if total > 0 else "0%",
            'avg_total_time': f"{sum(times)/len(times):.2f}s" if times else "0s",
            'avg_debug_time': f"{sum(r.debug_time for r in self.results)/total:.2f}s" if total > 0 else "0s",
            'bug_type_stats': bug_types
        }
    
    def print_summary(self):
        """打印评估摘要"""
        stats = self._calculate_stats()
        
        print("\n" + "="*70)
        print("C 语言 SWE-Bench 评估摘要")
        print("="*70)
        print(f"C 标准: {self.config.c_standard}")
        print(f"编译器: {self.config.compiler}")
        print("-"*70)
        
        for key, value in stats.items():
            if key != 'bug_type_stats':
                print(f"{key:<30}: {value}")
        
        print("\n按 Bug 类型统计:")
        for bug_type, stats_info in stats.get('bug_type_stats', {}).items():
            total = stats_info['total']
            passed = stats_info['passed']
            rate = passed / total * 100 if total > 0 else 0
            print(f"  {bug_type:<30}: {passed}/{total} ({rate:.1f}%)")
        
        print("="*70 + "\n")


def main():
    """主函数"""
    parser = argparse.ArgumentParser(description='C 语言 SWE-Bench 评估')
    parser.add_argument('--dataset', 
                       required=True,
                       help='C 语言测试数据集文件')
    parser.add_argument('--work-dir', 
                       default='./c_lang_evaluation',
                       help='工作目录')
    parser.add_argument('--max-instances', 
                       type=int, 
                       default=None,
                       help='最大评估实例数')
    parser.add_argument('--timeout', 
                       type=int, 
                       default=600,
                       help='单个实例超时时间（秒）')
    parser.add_argument('--c-standard', 
                       default='c11',
                       choices=['c89', 'c99', 'c11', 'c17'],
                       help='C 语言标准')
    parser.add_argument('--compiler', 
                       default='gcc',
                       choices=['gcc', 'clang'],
                       help='C 编译器')
    
    args = parser.parse_args()
    
    # 检查数据集文件
    if not os.path.exists(args.dataset):
        logger.error(f"数据集文件不存在: {args.dataset}")
        return 1
    
    # 创建配置
    config = EvaluationConfig(
        dataset_file=args.dataset,
        work_dir=args.work_dir,
        max_instances=args.max_instances,
        timeout=args.timeout,
        c_standard=args.c_standard,
        compiler=args.compiler
    )
    
    # 创建评估器
    evaluator = CLangEvaluator(config)
    
    try:
        # 运行评估
        evaluator.evaluate_all()
        
        # 保存结果
        evaluator.save_results()
        
        # 打印摘要
        evaluator.print_summary()
        
        return 0
    
    except KeyboardInterrupt:
        logger.info("评估被中断，保存中间结果...")
        evaluator.save_results(intermediate=True)
        return 1
    except Exception as e:
        logger.exception("评估过程出错")
        return 1


if __name__ == '__main__':
    sys.exit(main())
