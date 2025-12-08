"""
方法描述生成器 - 使用大模型为METHOD节点生成描述
"""
import os
import json
import time
from typing import Optional, Dict, Any


class MethodDescriptionGenerator:
    """使用大模型为方法生成描述"""
    
    def __init__(self, llm_config: Optional[Dict[str, Any]] = None):
        """
        初始化描述生成器
        
        Args:
            llm_config: 大模型配置，包含API密钥、模型名称等
        """
        self.llm_config = llm_config or self._get_default_config()
        self.cache = {}  # 缓存已生成的描述，避免重复调用
        
        # 设置编码环境
        self._setup_encoding()
        
        # 加载现有缓存
        self.load_cache()
    
    def _setup_encoding(self):
        """设置编码环境，解决Windows下的编码问题"""
        try:
            import sys
            import locale
            
            # 设置标准输出编码
            if hasattr(sys.stdout, 'reconfigure'):
                sys.stdout.reconfigure(encoding='utf-8')
            if hasattr(sys.stderr, 'reconfigure'):
                sys.stderr.reconfigure(encoding='utf-8')
            
            # 设置环境变量
            os.environ['PYTHONIOENCODING'] = 'utf-8'
            os.environ['LANG'] = 'en_US.UTF-8'
            
        except Exception as e:
            print(f"设置编码环境时出错: {e}")
        
    def _get_default_config(self) -> Dict[str, Any]:
        """获取默认的大模型配置"""
        # 尝试从setting.json加载配置
        try:
            import json
            setting_path = os.path.join(os.path.dirname(__file__), '..', '..', '..', '..', 'apps', 'codexgraph_agent', 'setting.json')
            if os.path.exists(setting_path):
                with open(setting_path, 'r', encoding='utf-8') as f:
                    settings = json.load(f)
                    setting_data = settings.get('setting', {})
                    if setting_data:
                        print(f"从setting.json加载配置: {setting_data}")
                        return {
                            'model_name': setting_data.get('llm_model_name', 'deepseek-coder'),
                            'api_key': os.getenv('OPENAI_API_KEY', 'sk-aabc879cff054d9fac7025eb491ef163'),
                            'base_url': os.getenv('OPENAI_BASE_URL', 'https://api.deepseek.com'),
                            'max_tokens': 200,
                            'temperature': setting_data.get('llm_temperature', 0.3)
                        }
        except Exception as e:
            print(f"加载setting.json配置失败: {e}")
        
        # 使用环境变量作为备选
        return {
            'model_name': 'deepseek-coder',  # 默认使用deepseek-coder
            'api_key': os.getenv('OPENAI_API_KEY', 'sk-aabc879cff054d9fac7025eb491ef163'),
            'base_url': os.getenv('OPENAI_BASE_URL', 'https://api.deepseek.com'),
            'max_tokens': 200,
            'temperature': 0.3
        }
    
    def generate_method_description(self, method_code: str, method_name: str, class_name: str = None, file_path: str = None, relations: dict = None) -> str:
        """
        为方法生成描述
        
        Args:
            method_code: 方法的完整代码
            method_name: 方法名称
            class_name: 所属类名（可选）
            file_path: 文件路径（可选）
            
        Returns:
            方法的描述文本
        """
        try:
            # 生成缓存键，使用更安全的方式
            import hashlib
            code_hash = hashlib.md5(method_code.encode('utf-8')).hexdigest()[:8]
            cache_key = f"{method_name}_{code_hash}"
            
            # 检查缓存
            if cache_key in self.cache:
                return self.cache[cache_key]
            
            try:
                # 构建提示词
                prompt = self._build_prompt(method_code, method_name, class_name, file_path, relations)
                
                # 调用大模型生成描述
                description = self._call_llm(prompt)
                
                # 缓存结果
                self.cache[cache_key] = description
                
                return description
                
            except Exception as e:
                print(f"生成方法描述失败: {e}")
                # 返回包含错误信息的描述
                error_description = f"方法 {method_name} 描述生成失败: {str(e)}"
                # 也缓存错误描述，避免重复尝试
                self.cache[cache_key] = error_description
                return error_description
                
        except Exception as e:
            # 最外层的异常处理，确保总是返回一个描述
            print(f"方法描述生成器发生严重错误: {e}")
            return f"方法 {method_name} 描述生成器错误: {str(e)}"
    
    def _build_prompt(self, method_code: str, method_name: str, 
                     class_name: str = None, file_path: str = None, relations: dict = None) -> str:
        """构建大模型提示词"""
        
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
        
        prompt = f"""请分析以下Python方法及其结构关系，用简洁的中文描述它的作用、功能及关键关系：\n\n{context_info}方法名: {method_name}\n方法代码:\n```python\n{method_code}\n```\n请用一句话概括该方法的主要作用，并指出其与其它方法/类的重要关系（若有）：\n描述："""
        
        return prompt
    
    def _call_llm(self, prompt: str) -> str:
        """调用大模型API"""
        try:
            print(f"尝试调用LLM API...")
            print(f"模型: {self.llm_config['model_name']}")
            print(f"API Base: {self.llm_config['base_url']}")
            print(f"API Key: {self.llm_config['api_key'][:10]}..." if self.llm_config['api_key'] else "无API Key")
            
            # 使用统一的LLM调用方式，兼容不同的API
            from modelscope_agent.llm import get_chat_model
            
            # 构建LLM配置
            llm_config = {
                'model': self.llm_config['model_name'],
                'api_base': self.llm_config['base_url'],
                'api_key': self.llm_config['api_key'],
                'model_server': 'openai'
            }
            
            print(f"LLM配置: {llm_config}")
            
            # 获取LLM实例
            llm = get_chat_model(
                model=self.llm_config['model_name'],
                model_server='openai',
                api_key=self.llm_config['api_key'],
                api_base=self.llm_config['base_url']
            )
            print(f"LLM实例创建成功: {type(llm)}")
            
            # 构建消息
            messages = [
                {"role": "system", "content": "你是一个专业的Python代码分析专家，擅长用简洁的中文语言描述代码功能。"},
                {"role": "user", "content": prompt}
            ]
            
            print(f"发送消息到LLM...")
            
            # 调用LLM
            response = llm.chat(messages=messages)
            
            print(f"LLM响应: {response[:100]}...")
            return response.strip()
            
        except ImportError as e:
            # 如果没有安装相关库，使用模拟响应
            print(f"警告: 未安装相关库，使用模拟描述: {e}")
            return self._generate_mock_description(prompt)
        except Exception as e:
            print(f"调用大模型API失败: {e}")
            import traceback
            traceback.print_exc()
            # 返回包含错误信息的描述
            return f"LLM调用失败: {str(e)}"
    
    def _generate_mock_description(self, prompt: str) -> str:
        """生成模拟描述（用于测试）"""
        try:
            # 简单的关键词匹配来生成描述
            if "方法代码:" in prompt and "```python" in prompt:
                method_code = prompt.split("方法代码:")[1].split("```python")[1].split("```")[0]
            else:
                return "该方法的具体功能需要进一步分析"
            
            print(f"模拟描述 - 分析代码: {method_code[:100]}...")
            
            # 更智能的代码分析
            method_code_lower = method_code.lower()
            
            # 检查方法名模式
            if "def __init__" in method_code:
                return "该方法用于初始化对象实例，设置对象的初始状态"
            elif "def __str__" in method_code or "def __repr__" in method_code:
                return "该方法用于返回对象的字符串表示"
            elif "def __len__" in method_code:
                return "该方法用于返回对象的长度"
            elif "def __get__" in method_code or "def __set__" in method_code:
                return "该方法用于属性访问控制"
            
            # 检查方法名关键词
            elif "def get_" in method_code_lower:
                return "该方法用于获取数据或信息"
            elif "def set_" in method_code_lower:
                return "该方法用于设置或修改数据"
            elif "def add_" in method_code_lower:
                return "该方法用于添加或增加数据"
            elif "def remove_" in method_code_lower or "def delete_" in method_code_lower:
                return "该方法用于删除或移除数据"
            elif "def update_" in method_code_lower:
                return "该方法用于更新数据"
            elif "def create_" in method_code_lower:
                return "该方法用于创建新对象或数据"
            elif "def find_" in method_code_lower or "def search_" in method_code_lower:
                return "该方法用于查找或搜索数据"
            elif "def calculate_" in method_code_lower or "def compute_" in method_code_lower:
                return "该方法用于执行计算操作"
            elif "def process_" in method_code_lower or "def handle_" in method_code_lower:
                return "该方法用于处理特定任务"
            elif "def check_" in method_code_lower or "def validate_" in method_code_lower:
                return "该方法用于检查或验证数据"
            elif "def save_" in method_code_lower or "def store_" in method_code_lower:
                return "该方法用于保存或存储数据"
            elif "def load_" in method_code_lower or "def read_" in method_code_lower:
                return "该方法用于加载或读取数据"
            
            # 检查代码内容关键词
            elif "return" in method_code and "if" in method_code:
                return "该方法用于条件判断并返回结果"
            elif "for" in method_code or "while" in method_code:
                return "该方法用于循环处理数据"
            elif "print" in method_code:
                return "该方法用于输出或显示信息"
            elif "open" in method_code and "file" in method_code_lower:
                return "该方法用于文件操作"
            elif "request" in method_code_lower or "http" in method_code_lower:
                return "该方法用于网络请求处理"
            elif "database" in method_code_lower or "db" in method_code_lower:
                return "该方法用于数据库操作"
            elif "json" in method_code_lower:
                return "该方法用于JSON数据处理"
            elif "list" in method_code_lower or "dict" in method_code_lower:
                return "该方法用于数据结构操作"
            elif "import" in method_code and "def" in method_code:
                return "该方法用于导入模块或执行特定功能"
            elif "return" in method_code:
                return "该方法用于返回计算结果或数据"
            elif "=" in method_code and "def" in method_code:
                return "该方法用于赋值或设置变量"
            else:
                # 基于方法名生成更通用的描述
                if "def " in method_code:
                    method_name = method_code.split("def ")[1].split("(")[0].strip()
                    if method_name:
                        return f"该方法名为 {method_name}，具体功能需要根据代码实现分析"
                
                return "该方法的具体功能需要进一步分析"
                
        except Exception as e:
            print(f"生成模拟描述时出错: {e}")
            return f"模拟描述生成失败: {str(e)}"
    
    def batch_generate_descriptions(self, methods: list) -> Dict[str, str]:
        """
        批量生成方法描述
        
        Args:
            methods: 方法列表，每个元素包含method_code, method_name, class_name等
            
        Returns:
            方法名到描述的映射
        """
        descriptions = {}
        
        for i, method in enumerate(methods):
            try:
                method_name = method.get('method_name', f'unknown_method_{i}')
                method_code = method.get('method_code', '')
                class_name = method.get('class_name', '')
                file_path = method.get('file_path', '')
                
                description = self.generate_method_description(
                    method_code, method_name, class_name, file_path
                )
                descriptions[method_name] = description
                
                # 添加延迟避免API限制
                time.sleep(0.1)
                
            except Exception as e:
                # 即使单个方法失败，也继续处理其他方法
                method_name = method.get('method_name', f'unknown_method_{i}')
                error_description = f"批量处理失败: {str(e)}"
                descriptions[method_name] = error_description
                print(f"处理方法 {method_name} 时出错: {e}")
        
        return descriptions
    
    def save_cache(self, cache_file: str = "method_descriptions_cache.json"):
        """保存缓存到文件"""
        try:
            with open(cache_file, 'w', encoding='utf-8') as f:
                json.dump(self.cache, f, ensure_ascii=False, indent=2)
            print(f"缓存已保存到: {cache_file}")
        except Exception as e:
            print(f"保存缓存失败: {e}")
    
    def load_cache(self, cache_file: str = "method_descriptions_cache.json"):
        """从文件加载缓存"""
        try:
            if os.path.exists(cache_file):
                with open(cache_file, 'r', encoding='utf-8') as f:
                    self.cache = json.load(f)
                print(f"已加载缓存: {len(self.cache)} 条记录")
        except Exception as e:
            print(f"加载缓存失败: {e}")
            self.cache = {}  # 初始化空缓存
    
    def clear_cache(self):
        """清空缓存"""
        self.cache.clear()
        print("缓存已清空")
    
    def get_cache_stats(self) -> Dict[str, int]:
        """获取缓存统计信息"""
        return {
            'total_cached': len(self.cache),
            'cache_size_bytes': len(str(self.cache).encode('utf-8'))
        }


# 全局描述生成器实例
_description_generator = None

def get_description_generator() -> MethodDescriptionGenerator:
    """获取全局描述生成器实例"""
    global _description_generator
    if _description_generator is None:
        _description_generator = MethodDescriptionGenerator()
    return _description_generator

def set_description_generator(generator: MethodDescriptionGenerator):
    """设置全局描述生成器实例"""
    global _description_generator
    _description_generator = generator
