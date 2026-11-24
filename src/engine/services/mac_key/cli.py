# -*- coding: utf-8 -*-
"""Diagnostic CLI.

    PYTHONPATH=src .venv/bin/python -m engine.services.mac_key [--db-dir PATH] [--probe]

``src`` is the directory containing the ``engine`` package (same convention as
``pytest.ini``'s ``pythonpath = src``). Read-only by default. ``--probe`` runs
the configured providers and reports how many keys pass HMAC verification,
without writing any config file.
"""
from __future__ import annotations

import argparse
import sys

from . import diagnostics

YES = "是"
NO = "否"
UNKNOWN = "未知"


def _yn(value) -> str:
    if value is None:
        return UNKNOWN
    return YES if value else NO


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="mac_key", description="macOS 密钥来源诊断（只读，不打印任何密钥）")
    parser.add_argument("--db-dir", default="", help="微信 db_storage 目录")
    parser.add_argument("--probe", action="store_true",
                        help="试跑已配置的 provider（不写配置）")
    args = parser.parse_args(argv)

    db_count = salt_count = None
    db_files = []
    if args.db_dir:
        from engine.db_key_crypto import collect_db_files
        db_files, salt_map = collect_db_files(args.db_dir)
        db_count, salt_count = len(db_files), len(salt_map)

    info = diagnostics.collect(args.db_dir, db_count, salt_count)
    print("=" * 62)
    print("macOS 密钥来源诊断（只读）")
    print("=" * 62)
    print(f"系统/架构      : {info['system']} / {info['arch']} (Python {info['python']})")
    print(f"提钥流程       : {info.get('mac_key_flow') or UNKNOWN} "
          f"(runtime={info.get('runtime_arch') or UNKNOWN}, "
          f"hardware={info.get('hardware_arch') or UNKNOWN})")
    print(f"微信版本       : {info['wechat_version'] or UNKNOWN} "
          f"→ profile {info.get('helper_mode') or UNKNOWN}")
    print(f"微信进程运行中 : {_yn(info['wechat_running'])}")
    print(f"SIP 已开启     : {_yn(info['sip_enabled'])}  "
          "（高级模式需临时关闭，完成后请重新开启）")
    inv = info.get("helper_inventory") or {}
    print(f"helper 资源    : legacy={_yn(inv.get('legacy'))} "
          f"4.1.13={_yn(inv.get('wechat_4_1_13'))} intel={_yn(inv.get('intel'))}")
    print(f"数据目录       : {info['db_dir'] or '未指定'}")
    if db_count is not None:
        print(f"加密库 / 密钥数: {db_count} / {salt_count}")
    mmkv = info["mmkv"]
    print(f"MMKV 文件      : {mmkv.get('files', 0)} 个，布局={mmkv.get('layout')}")
    if mmkv.get("note"):
        print(f"                {mmkv['note']}")
    print("-" * 62)
    for status in info["providers"]:
        state = "可用" if status.get("available") else "未启用"
        print(f"provider {status['name']:<18} {state}  {status.get('reason') or ''}")
    print(f"高级模式就绪   : {_yn(info['auto_extract_ready'])}   "
          f"可立即执行: {_yn(info.get('capture_ready'))}")
    print("-" * 62)
    for line in diagnostics.recommendations(info):
        print(f"• {line}")

    if args.probe:
        if not db_files:
            print("\n[probe] 需要 --db-dir 才能做 HMAC 校验")
            return 1
        from .adapter import extract_keys_via_mac_provider
        key_map: dict[str, str] = {}
        salt_to_dbs: dict[str, list[str]] = {}
        for rel, _p, _s, salt, _page1 in db_files:
            salt_to_dbs.setdefault(salt, []).append(rel)
        found = extract_keys_via_mac_provider(
            args.db_dir, db_files, salt_to_dbs, key_map, print)
        print(f"\n[probe] HMAC 校验通过 {found}/{len(salt_to_dbs)} 个密钥（未写入配置）")
    print("=" * 62)
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
