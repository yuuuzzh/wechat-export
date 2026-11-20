# -*- coding: utf-8 -*-
"""Example drop-in exporter: one JSON object per line.

Copy/rename this file under plugins/exporters/ and edit FORMAT / export().
"""
from __future__ import annotations

import json

FORMAT = 'example-jsonl'
LABEL = '示例 JSONL 插件'
EXT = 'jsonl'
MERGE = True


def export(messages, meta, out_path, **kwargs):
    with open(out_path, 'w', encoding='utf-8') as f:
        f.write(json.dumps({'meta': meta}, ensure_ascii=False) + '\n')
        for m in messages:
            f.write(json.dumps({
                't': m.get('timestamp'),
                'sender': m.get('sender'),
                'chat': m.get('chat_name'),
                'type': m.get('type_name'),
                'text': m.get('text'),
            }, ensure_ascii=False) + '\n')
    return out_path
