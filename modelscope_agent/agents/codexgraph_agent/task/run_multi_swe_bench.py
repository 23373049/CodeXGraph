"""Batch runner for evaluating CodexGraph code_chat on Multi-SWE-bench data."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Dict, Iterator, List, Tuple

from modelscope_agent.agents.codexgraph_agent.task.code_chat import (
    CodexGraphAgentChat,
)
from modelscope_agent.environment.graph_database.graph_database import (
    GraphDatabaseHandler,
)


PROJECT_ROOT = Path(__file__).resolve().parents[4]
DEFAULT_PROMPT_PATH = PROJECT_ROOT / 'apps' / 'codexgraph_agent' / 'prompt' / 'code_chat'
DEFAULT_SCHEMA_PATH = (
    PROJECT_ROOT / 'apps' / 'codexgraph_agent' / 'prompt' / 'graph_database'
)
DEFAULT_OUTPUT_ROOT = PROJECT_ROOT / 'outputs' / 'multi_swe_bench'


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description='Run CodexGraph code_chat agent across Multi-SWE-bench datasets.'
    )
    parser.add_argument(
        '--dataset',
        required=True,
        help='Path to a JSONL dataset file or a directory that contains JSONL files.',
    )
    parser.add_argument(
        '--language',
        default='c',
        help='Language hint passed to the agent (default: c).',
    )
    parser.add_argument(
        '--llm-config',
        required=True,
        help='Path to a JSON file describing the LLM configuration (model, endpoint, api_key, etc.).',
    )
    parser.add_argument(
        '--graph-config',
        required=True,
        help='Path to a JSON file containing graph configuration: uri, user, password, and optional database_name.',
    )
    parser.add_argument(
        '--output-dir',
        default=str(DEFAULT_OUTPUT_ROOT),
        help='Directory to store evaluation outputs (default: outputs/multi_swe_bench).',
    )
    parser.add_argument(
        '--prompt-path',
        default=str(DEFAULT_PROMPT_PATH),
        help='Prompt directory for CodexGraph agent (default: apps/codexgraph_agent/prompt).',
    )
    parser.add_argument(
        '--schema-path',
        default=str(DEFAULT_SCHEMA_PATH),
        help='Schema directory for CodexGraph agent (default: prompt/graph_database).',
    )
    parser.add_argument(
        '--task-id',
        default='multi_swe_bench',
        help='Task label used for graph namespace isolation.',
    )
    parser.add_argument(
        '--max-iterations',
        type=int,
        default=3,
        help='Maximum reasoning iterations for the agent (default: 3).',
    )
    parser.add_argument(
        '--limit',
        type=int,
        default=None,
        help='Optional limit of instances per dataset file.',
    )
    parser.add_argument(
        '--resume',
        action='store_true',
        help='Append to existing output files instead of overwriting (default: overwrite).',
    )
    return parser.parse_args()


def load_json_config(path: Path) -> Dict[str, object]:
    with path.open('r', encoding='utf-8') as f:
        return json.load(f)


def discover_jsonl(dataset_path: Path) -> List[Path]:
    if dataset_path.is_file() and dataset_path.suffix == '.jsonl':
        return [dataset_path]
    if dataset_path.is_dir():
        return sorted(p for p in dataset_path.glob('*.jsonl') if p.is_file())
    raise FileNotFoundError(f'No JSONL files found at {dataset_path}')


def iter_jsonl(path: Path) -> Iterator[Tuple[int, Dict[str, object]]]:
    with path.open('r', encoding='utf-8') as f:
        for idx, line in enumerate(f, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                yield idx, json.loads(line)
            except json.JSONDecodeError as exc:
                print(f'[warn] {path.name}: line {idx} JSON decode error: {exc}')


def build_issue_prompt(sample: Dict[str, object]) -> str:
    title = sample.get('title') or ''
    body = sample.get('body') or ''
    resolved = sample.get('resolved_issues')
    resolved_repr = json.dumps(resolved, ensure_ascii=False, indent=2) if resolved else '[]'
    lines: List[str] = []
    if title:
        lines.append(f'Title: {title}')
    if body:
        lines.append('Body:\n' + body.strip())
    lines.append('Resolved issues:')
    lines.append(resolved_repr)
    issue_block = '\n\n'.join(lines)
    question = (
        '<issue>\n'
        f'{issue_block}\n'
        '</issue>\n'
        '请分析上述问题并给出修复建议，必要时说明需要的代码上下文。'
    )
    return question


def ensure_output_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def main() -> None:
    args = parse_args()

    dataset_path = Path(args.dataset).resolve()
    jsonl_files = discover_jsonl(dataset_path)
    if not jsonl_files:
        raise SystemExit(f'No JSONL files discovered in {dataset_path}')

    llm_config_path = Path(args.llm_config).resolve()
    graph_config_path = Path(args.graph_config).resolve()

    llm_config = load_json_config(llm_config_path)
    graph_config = load_json_config(graph_config_path)

    output_root = Path(args.output_dir).resolve()
    ensure_output_dir(output_root)

    graph_db = GraphDatabaseHandler(
        graph_config['uri'],
        graph_config['user'],
        graph_config['password'],
        database_name=graph_config.get('database_name', 'neo4j'),
        task_id=args.task_id,
    )

    agent = CodexGraphAgentChat(
        llm=llm_config,
        prompt_path=args.prompt_path,
        schema_path=args.schema_path,
        task_id=args.task_id,
        graph_db=graph_db,
        language=args.language,
        max_iterations=args.max_iterations,
        message_callback=None,
    )

    print(f'[info] Loaded {len(jsonl_files)} dataset file(s) from {dataset_path}')
    print(f'[info] Output directory: {output_root}')

    try:
        for jsonl_file in jsonl_files:
            limit = args.limit if args.limit and args.limit > 0 else None
            processed = 0
            dataset_name = jsonl_file.stem
            output_path = output_root / f'{dataset_name}_results.jsonl'
            mode = 'a' if args.resume else 'w'
            with output_path.open(mode, encoding='utf-8') as out_fp:
                for line_idx, sample in iter_jsonl(jsonl_file):
                    if limit is not None and processed >= limit:
                        break

                    question = build_issue_prompt(sample)
                    instance_id = sample.get('instance_id') or sample.get('number')
                    metadata = {
                        'dataset_file': jsonl_file.name,
                        'line_index': line_idx,
                        'instance_id': instance_id,
                        'language': args.language,
                    }
                    try:
                        answer = agent.run(question)
                        error = None
                    except Exception as exc:  # pylint: disable=broad-except
                        answer = f'[ERROR] {exc}'
                        error = repr(exc)
                        print(f'[error] {jsonl_file.name} line {line_idx}: {exc}')

                    history = agent.get_chat_history()
                    output_record = {
                        'metadata': metadata,
                        'question': question,
                        'answer': answer,
                        'chat_history': history,
                        'resolved_issues': sample.get('resolved_issues'),
                        'run_result': sample.get('run_result'),
                        'error': error,
                    }
                    out_fp.write(json.dumps(output_record, ensure_ascii=False) + '\n')
                    out_fp.flush()

                    processed += 1
                    print(
                        f'[info] {dataset_name}: processed {processed} sample(s)'
                        + (f' (limit {limit})' if limit else ''),
                        end='\r',
                    )
            print(f'\n[done] {dataset_name}: total {processed} sample(s) processed -> {output_path}')
    finally:
        try:
            graph_db.graph.close()
        except Exception:  # pylint: disable=broad-except
            pass


if __name__ == '__main__':
    main()
