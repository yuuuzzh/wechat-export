# -*- coding: utf-8 -*-
"""Drop-in Python exporter plugins.

Place scripts under either:
  - ``<project_or_exe>/plugins/exporters/*.py``
  - directory from config key ``plugins_dir`` (optional)

Each module should define::

    FORMAT = 'myfmt'          # format id used in API / UI
    LABEL = '我的格式'         # optional display name
    EXT = 'txt'               # optional default extension

    def export(messages, meta, out_path, **kwargs):
        '''Write messages to out_path; return out_path or raise.'''
        ...

Optional: ``MERGE = True`` to treat as always-merged single-file format.
"""
from __future__ import annotations

import importlib.util
import json
import os
import sys
import traceback
from typing import Any, Optional


_Plugin = dict[str, Any]
_CACHE: dict[str, _Plugin] = {}
_LOADED_DIRS: list[str] = []


def _read_cfg() -> dict:
    try:
        from engine.config_file import _config_path
        path = _config_path()
        if os.path.isfile(path):
            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            return data if isinstance(data, dict) else {}
    except Exception:
        pass
    return {}


def default_plugin_dirs() -> list[str]:
    """Resolve searchable plugin directories (exe-adjacent preferred)."""
    dirs: list[str] = []
    try:
        from engine.config_file import _config_path
        root = os.path.dirname(_config_path())
        dirs.append(os.path.join(root, 'plugins', 'exporters'))
    except Exception:
        pass

    cfg = _read_cfg()
    extra = (cfg.get('plugins_dir') or '').strip()
    if extra:
        dirs.insert(0, extra)
        dirs.insert(0, os.path.join(extra, 'exporters'))

    # Repo layout when running from source
    here = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..'))
    dirs.append(os.path.join(here, 'plugins', 'exporters'))

    seen = set()
    out = []
    for d in dirs:
        ab = os.path.abspath(d)
        if ab not in seen:
            seen.add(ab)
            out.append(ab)
    return out


def _load_module(path: str):
    name = f'wechat_exp_plugin_{os.path.splitext(os.path.basename(path))[0]}'
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        return None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def discover_plugins(force: bool = False) -> dict[str, _Plugin]:
    """Scan plugin dirs; return {format_id: plugin_dict}."""
    global _CACHE, _LOADED_DIRS
    dirs = default_plugin_dirs()
    if not force and _CACHE and _LOADED_DIRS == dirs:
        return dict(_CACHE)

    found: dict[str, _Plugin] = {}
    for d in dirs:
        if not os.path.isdir(d):
            continue
        try:
            names = sorted(os.listdir(d))
        except OSError:
            continue
        for name in names:
            if not name.endswith('.py') or name.startswith('_'):
                continue
            path = os.path.join(d, name)
            try:
                mod = _load_module(path)
            except Exception:
                traceback.print_exc()
                continue
            if mod is None:
                continue
            fmt = (getattr(mod, 'FORMAT', None) or '').strip().lower()
            export_fn = getattr(mod, 'export', None)
            if not fmt or not callable(export_fn):
                continue
            if fmt in found:
                continue  # first wins
            found[fmt] = {
                'format': fmt,
                'label': getattr(mod, 'LABEL', None) or fmt,
                'ext': (getattr(mod, 'EXT', None) or 'txt').lstrip('.'),
                'merge': bool(getattr(mod, 'MERGE', True)),
                'export': export_fn,
                'path': path,
            }
    _CACHE = found
    _LOADED_DIRS = dirs
    return dict(found)


def list_plugin_formats() -> list[dict[str, str]]:
    return [
        {
            'format': p['format'],
            'label': p['label'],
            'ext': p['ext'],
            'source': p['path'],
        }
        for p in discover_plugins().values()
    ]


def get_plugin(fmt: str) -> Optional[_Plugin]:
    fmt = (fmt or '').strip().lower()
    return discover_plugins().get(fmt)


def run_plugin(
    fmt: str,
    messages: list[dict],
    meta: dict,
    out_path: str,
    **kwargs,
) -> str:
    plugin = get_plugin(fmt)
    if not plugin:
        raise ValueError(f'未知插件格式: {fmt}')
    result = plugin['export'](messages, meta, out_path, **kwargs)
    return result or out_path
