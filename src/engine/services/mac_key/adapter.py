# -*- coding: utf-8 -*-
"""Strategy adapter: macOS providers -> the project's ``{salt: 64hex}`` contract.

Signature is intentionally identical to the Windows strategies in
``wechat_key_extract`` so the orchestrator stays agnostic::

    (db_dir, db_files, salt_to_dbs, key_map, print_fn, progress_fn) -> int

Every candidate is verified against the real database page-1 HMAC before it
enters ``key_map``. Nothing is persisted here; ``save_key_results`` remains the
single write point.
"""
from __future__ import annotations

import sys
from typing import Callable

from engine.db_key_crypto import verify_enc_key

from .contract import mask_key
from .providers import available_providers, provider_statuses

MAX_CANDIDATES = 256


def extract_keys_via_mac_provider(db_dir, db_files, salt_to_dbs, key_map,
                                  print_fn: Callable[[str], None] = print,
                                  progress_fn=None) -> int:
    """Try configured macOS providers. Returns the number of newly verified salts."""
    if sys.platform != "darwin":
        return 0
    if progress_fn:
        progress_fn(30, "检查 macOS 密钥来源...")

    ready = available_providers(db_dir)
    if not ready:
        for status in provider_statuses(db_dir):
            print_fn(f"[MacKey] {status['name']}: 不可用（{status.get('reason') or '未知'}）")
        print_fn("[MacKey] 未启用自动提钥。已有密钥请用「手动输入密钥」，或打开已解密备份。")
        return 0

    pending = {salt: page1 for _rel, _path, _sz, salt, page1 in db_files
               if salt not in key_map}
    if not pending:
        return 0

    found = 0
    account_only_seen = False
    for provider, _status in ready:
        result = provider.extract(db_dir, print_fn)
        if not result.ok:
            print_fn(f"[MacKey] {provider.name} 失败 [{result.code}]：{result.message}")
            continue

        for candidate in result.candidates[:MAX_CANDIDATES]:
            if candidate.kind == "account":
                account_only_seen = True
            enc_key = bytes.fromhex(candidate.key_hex)
            if candidate.salt_hex and candidate.salt_hex in pending:
                targets = [(candidate.salt_hex, pending[candidate.salt_hex])]
            elif candidate.salt_hex:
                continue  # explicit salt that we do not need -> skip
            else:
                targets = list(pending.items())

            for salt, page1 in targets:
                if salt in key_map:
                    continue
                if verify_enc_key(enc_key, page1):
                    key_map[salt] = candidate.key_hex
                    del pending[salt]
                    found += 1
                    print_fn(f"[MacKey-HIT] {provider.name} salt={salt[:8]}… "
                             f"key={mask_key(candidate.key_hex)} "
                             f"profile={candidate.profile or '-'}")
        if not pending:
            break

    if not found and account_only_seen:
        print_fn("[MacKey] helper 返回的是账号级密钥，逐个数据库的 HMAC 均未通过；"
                 "可能需要「主密钥 + DB salt → 每库密钥」的派生层。")
    print_fn(f"[MacKey] 校验通过 {found} 个密钥，剩余 {len(pending)} 个 salt 未解")
    return found
