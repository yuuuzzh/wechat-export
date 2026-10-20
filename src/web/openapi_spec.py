# -*- coding: utf-8 -*-
"""Build an OpenAPI 3 document from the live Flask URL map.

Scripts can fetch ``GET /api/openapi.json``. The spec is generated from
registered ``/api/*`` rules (methods, path params, docstring, and a light
scan of ``request.args`` / JSON body usage). It does not replace hand-written
examples in ``docs/HTTP-API.md``.
"""
from __future__ import annotations

import inspect
import re
from typing import Any

_PARAM_RE = re.compile(r'<(?:(?P<conv>\w+):)?(?P<name>\w+)>')
_ARGS_RE = re.compile(
    r"""request\.args\.get\(\s*['"]([A-Za-z_][\w-]*)['"]"""
)
_HTTP_METHODS = ('get', 'post', 'put', 'patch', 'delete')


def _openapi_path(rule: str) -> tuple[str, list[dict[str, Any]]]:
    params: list[dict[str, Any]] = []

    def _sub(match: re.Match) -> str:
        conv = (match.group('conv') or 'string').lower()
        name = match.group('name')
        if conv in ('int', 'float'):
            schema: dict[str, Any] = {'type': 'integer' if conv == 'int' else 'number'}
        else:
            schema = {'type': 'string'}
        params.append({
            'name': name,
            'in': 'path',
            'required': True,
            'schema': schema,
        })
        return '{' + name + '}'

    return _PARAM_RE.sub(_sub, rule), params


def _view_source(func) -> str:
    try:
        return inspect.getsource(func) or ''
    except (OSError, TypeError):
        return ''


def _doc_bits(func) -> tuple[str, str]:
    doc = (inspect.getdoc(func) or '').strip()
    if not doc:
        name = getattr(func, '__name__', 'operation')
        return name.replace('_', ' '), ''
    lines = doc.splitlines()
    summary = lines[0].strip()
    description = '\n'.join(lines[1:]).strip()
    return summary[:180], description


def _query_params(source: str) -> list[dict[str, Any]]:
    seen = []
    for name in _ARGS_RE.findall(source):
        if name not in seen:
            seen.append(name)
    return [
        {
            'name': name,
            'in': 'query',
            'required': False,
            'schema': {'type': 'string'},
        }
        for name in seen
    ]


def _tag_for(endpoint: str, path: str) -> str:
    if endpoint and '.' in endpoint:
        return endpoint.split('.', 1)[0]
    parts = [p for p in path.split('/') if p and not p.startswith('{')]
    if len(parts) >= 2 and parts[0] == 'api':
        return parts[1]
    return 'api'


def build_openapi(app, *, version: str = '0.0.0') -> dict[str, Any]:
    """Return an OpenAPI 3.0 document for ``/api/*`` routes on ``app``."""
    paths: dict[str, dict[str, Any]] = {}
    tags_seen: dict[str, None] = {}

    for rule in app.url_map.iter_rules():
        path_raw = rule.rule or ''
        if not path_raw.startswith('/api'):
            continue
        if path_raw.startswith('/api/openapi'):
            continue
        methods = [
            m.lower() for m in (rule.methods or [])
            if m.lower() in _HTTP_METHODS
        ]
        if not methods:
            continue
        path, path_params = _openapi_path(path_raw)
        func = app.view_functions.get(rule.endpoint)
        source = _view_source(func) if func else ''
        summary, description = _doc_bits(func) if func else (rule.endpoint, '')
        tag = _tag_for(rule.endpoint or '', path)
        tags_seen[tag] = None
        query = _query_params(source)
        is_sse = 'create_sse_progress' in source or 'text/event-stream' in source
        accepts_json = 'get_json' in source

        op_path = paths.setdefault(path, {})
        for method in methods:
            parameters = list(path_params) + list(query)
            operation: dict[str, Any] = {
                'operationId': f"{(rule.endpoint or method).replace('.', '_')}_{method}",
                'summary': summary,
                'tags': [tag],
                'responses': {
                    '200': {
                        'description': 'SSE 进度流' if is_sse else '成功',
                        'content': {
                            ('text/event-stream' if is_sse else 'application/json'): {
                                'schema': {
                                    'type': 'string' if is_sse else 'object',
                                    'additionalProperties': True,
                                }
                            }
                        },
                    }
                },
            }
            if description:
                operation['description'] = description
            if parameters:
                operation['parameters'] = parameters
            if accepts_json and method in ('post', 'put', 'patch'):
                operation['requestBody'] = {
                    'required': False,
                    'content': {
                        'application/json': {
                            'schema': {
                                'type': 'object',
                                'additionalProperties': True,
                            }
                        }
                    },
                }
            op_path[method] = operation

    return {
        'openapi': '3.0.3',
        'info': {
            'title': 'WeChat Export HTTP API',
            'version': version or '0.0.0',
            'description': (
                '由当前进程已注册的 /api/* 路由自动生成。'
                '仅监听本机、无鉴权，请勿对公网开放。'
                '带 SSE 的接口返回 text/event-stream。'
            ),
        },
        'servers': [{'url': '/'}],
        'tags': [{'name': name} for name in sorted(tags_seen)],
        'paths': dict(sorted(paths.items())),
    }
