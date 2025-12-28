"""Shared function planning helpers for CodexGraph agents."""
from __future__ import annotations

import inspect
import json
import os
import time
from typing import Any, Dict, List, Optional


class FunctionPlanningMixin:
    """Provide reusable function schemas and execution utilities."""

    # 1. 定义多个function schema
    FUNCTIONS: List[Dict[str, Any]] = [
        {
            "name": "find_nodes_in_file",
            "description": (
                "按文件路径或文件名检索图谱：返回该文件下的所有模块、类、函数等节点及代码片段。"
                "仅在用户明确指定文件、模块路径或希望浏览单个文件的全部内容时使用。"
                "示例：'请列出code_chat.py文件的所有节点' -> keyword='code_chat.py'"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "keyword": {"type": "string", "description": "要查找的文件名或路径，如code_chat.py"}
                },
                "required": ["keyword"]
            }
        },
        {
            "name": "find_class_by_keyword",
            "description": (
                "在所有类/结构体名称中查找包含指定关键字的节点，并返回定义位置和代码。"
                "用于用户询问'有哪些类名包含X'、'存在某个类吗'、'查找带Agent的类'等命名层面的搜索。"
                "示例：'查找所有包含Graph的类' -> keyword='Graph'"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "keyword": {"type": "string", "description": "类名关键词，如Agent"}
                },
                "required": ["keyword"]
            }
        },
        {
            "name": "find_function_by_keyword",
            "description": (
                "在所有函数/方法名称中匹配给定关键字，返回签名、文件路径与代码。"
                "适合回答'有没有名为X的函数''列出名称包含run的函数'等与函数命名直接相关的问题。"
                "示例：'查找所有包含call的函数' -> keyword='call'"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "keyword": {"type": "string", "description": "函数名关键词，如run"}
                },
                "required": ["keyword"]
            }
        },
        {
            "name": "introduce_entity",
            "description": (
                "根据名称模糊匹配实体（模块/类/函数等），再由 LLM 生成面向用户的中文讲解。"
                "当用户需求是'介绍/解释/说明某个实体是什么、做什么、如何工作'时优先使用此工具。"
                "示例：'请介绍code_chat模块' -> keyword='code_chat'；'explain code_chat' -> keyword='code_chat'"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "keyword": {"type": "string", "description": "要介绍的实体名，如code_chat"}
                },
                "required": ["keyword"]
            }
        },
        {
            "name": "find_references",
            "description": (
                "检索目标实体在图谱中的上下游引用关系，返回调用者/被调用者及关系类型。"
                "用于回答'谁调用了这个函数''该类在哪被使用''查看依赖关系'等问题。"
                "示例：'查找引用 code_chat' -> keyword='code_chat'"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "keyword": {"type": "string", "description": "要查找引用的实体名关键词，如code_chat"}
                },
                "required": ["keyword"]
            }
        },
        {
            "name": "find_function_by_description",
            "description": (
                "按功能/行为关键字在节点描述（description）中搜索，定位相关模块/类/函数并返回说明与代码。"
                "当用户描述某个业务能力或动作（如'登录''鉴权''上传'）而不清楚具体名称时，使用该工具。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "keyword": {"type": "string", "description": "功能或能力的关键词，例如 '登录'、'鉴权'、'上传'"}
                },
                "required": ["keyword"]
            }
        },
    ]

    # 2. 本地实现每个function，返回Cypher
    def find_nodes_in_file(self, keyword: str) -> str:
        return f"MATCH (n) WHERE n.file_path CONTAINS '{keyword}' RETURN labels(n) AS node_type, n.name, n.file_path, n"

    def _label_map(self) -> Dict[str, str]:
        """返回当前 agent 语言对应的标签映射。"""
        lang = (getattr(self, 'language', '') or '').lower()
        if lang.startswith('c'):
            return {
                'class_label': 'STRUCT',
                'module_label': 'FILE',
                'method_label': 'FUNCTION',
                'field_label': 'STRUCT_MEMBER',
                'function_label': 'FUNCTION'
            }
        return {
            'class_label': 'CLASS',
            'module_label': 'MODULE',
            'method_label': 'FUNCTION',
            'field_label': 'FIELD',
            'function_label': 'FUNCTION'
        }

    def find_class_by_keyword(self, keyword: str) -> str:
        labels = self._label_map()
        class_label = labels.get('class_label', 'CLASS')
        return f"MATCH (c:{class_label}) WHERE c.name CONTAINS '{keyword}' RETURN c.name, c.file_path, c.signature, c.code"

    def find_function_by_keyword(self, keyword: str) -> str:
        labels = self._label_map()
        method_label = labels.get('method_label', 'FUNCTION')
        return f"MATCH (f:{method_label}) WHERE f.name CONTAINS '{keyword}' RETURN f.name, f.file_path, f.signature, f.code"

    def introduce_entity(self, keyword: str) -> str:
        return f"MATCH (n) WHERE n.name CONTAINS '{keyword}' RETURN labels(n) AS node_type, n.name, n.file_path, n.code"

    def find_references(self, keyword: str) -> str:
        return (
            f"MATCH (t) WHERE t.name CONTAINS '{keyword}' \n"
            "MATCH (a)-[r]->(t) RETURN labels(a) AS from_labels, a.name AS from_name, type(r) AS rel, labels(t) AS to_labels, t.name AS to_name, t.file_path AS to_file"
        )

    def find_function_by_description(self, keyword: str) -> str:
        return (
            f"MATCH (n) "
            f"WHERE (exists(n.description) AND toLower(coalesce(n.description,'')) CONTAINS toLower('{keyword}')) "
            "RETURN labels(n) AS node_type, n.name AS name, n.file_path AS file_path, n.signature AS signature, "
            "n.description AS description, n.code AS code "
            "LIMIT 200"
        )