"""有界本地标注集；校验错误和对象 repr 不携带问题、标签或路径。"""

from dataclasses import dataclass, field
import json
import os
from pathlib import Path
import re
import stat
from typing import Any

from jsonschema import Draft202012Validator

from app.modules.knowledge.vector_contract import fingerprint


MAX_DATASET_BYTES = 2 * 1024 * 1024
UUID_PATTERN = r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
IDENTIFIER = {'type': 'string', 'pattern': r'^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$'}
CATEGORIES = ('paraphrase', 'error_code', 'domain_term', 'long_description',
              'cross_project', 'no_answer', 'pipeline_probe', 'other')


class EvaluationError(ValueError):
    def __init__(self, code: str = 'knowledge_evaluation_dataset_invalid') -> None:
        super().__init__(code)
        self.code = code


def _object(properties: dict[str, Any]) -> dict[str, Any]:
    return {'type': 'object', 'additionalProperties': False,
            'required': list(properties), 'properties': properties}


DATASET_SCHEMA = {
    '$schema': 'https://json-schema.org/draft/2020-12/schema',
    **_object({
        'contract': {'const': 'knowledge-evaluation/v1'},
        'dataset_version': IDENTIFIER,
        'basis': {'enum': ['human', 'synthetic', 'self_query']},
        'labels_complete': {'type': 'boolean'},
        'knowledge_base_code': IDENTIFIER,
        'source_id': {'type': 'string', 'pattern': UUID_PATTERN},
        'annotation': _object({
            'origin': {'enum': ['human_reviewed', 'synthetic_fixture', 'pipeline_probe']},
            'reviewed': {'const': True, 'type': 'boolean'},
        }),
        'cases': {'type': 'array', 'minItems': 1, 'maxItems': 500, 'items': _object({
            'query_id': IDENTIFIER,
            'query': {'type': 'string', 'minLength': 1, 'maxLength': 2000},
            'category': {'enum': list(CATEGORIES)},
            'no_answer': {'type': 'boolean'},
            'relevant': {'type': 'array', 'maxItems': 100, 'uniqueItems': True,
                         'items': _object({'kind': {'enum': ['document', 'work_item']},
                                           'id': IDENTIFIER})},
        })},
    }),
}


@dataclass(frozen=True, repr=False)
class EvaluationCase:
    query_id: str
    query: str
    category: str
    no_answer: bool
    relevant: tuple[tuple[str, str], ...]


@dataclass(frozen=True, repr=False)
class EvaluationDataset:
    version: str
    basis: str
    labels_complete: bool
    base_code: str
    source_id: str
    cases: tuple[EvaluationCase, ...]
    digest: str = field(repr=False)


def parse_dataset(value: Any) -> EvaluationDataset:
    # Do not stringify ValidationError: it contains the failing business input.
    if not Draft202012Validator(DATASET_SCHEMA).is_valid(value):
        raise EvaluationError()
    expected_origin = {'human': 'human_reviewed', 'synthetic': 'synthetic_fixture',
                       'self_query': 'pipeline_probe'}[value['basis']]
    if value['annotation']['origin'] != expected_origin:
        raise EvaluationError()
    cases = []
    seen = set()
    for row in value['cases']:
        if (row['query_id'] in seen or not row['query'].strip()
                or row['no_answer'] != (not row['relevant'])
                or (value['basis'] == 'self_query') != (row['category'] == 'pipeline_probe')):
            raise EvaluationError()
        seen.add(row['query_id'])
        for ref in row['relevant']:
            if ref['kind'] == 'document' and not re.fullmatch(UUID_PATTERN, ref['id']):
                raise EvaluationError()
        cases.append(EvaluationCase(row['query_id'], row['query'], row['category'],
                                    row['no_answer'], tuple((r['kind'], r['id']) for r in row['relevant'])))
    return EvaluationDataset(value['dataset_version'], value['basis'], value['labels_complete'],
                             value['knowledge_base_code'], value['source_id'], tuple(cases), fingerprint(value))


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise EvaluationError()
        result[key] = value
    return result


def load_dataset(path: Path) -> EvaluationDataset:
    """Require an owner-only directory/file; no symlink, device, FIFO or oversized input."""
    try:
        parent = path.parent.stat()
        if not stat.S_ISDIR(parent.st_mode) or stat.S_IMODE(parent.st_mode) & 0o077:
            raise EvaluationError('knowledge_evaluation_input_permissions')
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(fd, 'rb') as stream:
            info = os.fstat(stream.fileno())
            if (not stat.S_ISREG(info.st_mode) or stat.S_IMODE(info.st_mode) & 0o077
                    or info.st_nlink != 1):
                raise EvaluationError('knowledge_evaluation_input_permissions')
            if info.st_size > MAX_DATASET_BYTES:
                raise EvaluationError('knowledge_evaluation_input_limit')
            data = stream.read(MAX_DATASET_BYTES + 1)
        if len(data) > MAX_DATASET_BYTES:
            raise EvaluationError('knowledge_evaluation_input_limit')
        return parse_dataset(json.loads(data, object_pairs_hook=_unique_object))
    except EvaluationError:
        raise
    except (OSError, ValueError, RecursionError):
        raise EvaluationError() from None
