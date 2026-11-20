# -*- coding: utf-8 -*-
"""Platform-neutral SQLCipher key helpers (HMAC verify + DB file scan).

Kept separate from Win32 process-memory extractors so macOS / Linux can
import manual-key and decrypt flows without loading ``ctypes.windll``.
"""
from __future__ import annotations

import hashlib
import hmac as hmac_mod
import os
import struct

PAGE_SZ = 4096
KEY_SZ = 32
SALT_SZ = 16


def verify_enc_key(enc_key: bytes, db_page1: bytes) -> bool:
    """Verify a 32-byte SQLCipher 4 key against the first database page."""
    if not enc_key or not db_page1 or len(db_page1) < PAGE_SZ:
        return False
    salt = db_page1[:SALT_SZ]
    mac_salt = bytes(b ^ 0x3A for b in salt)
    mac_key = hashlib.pbkdf2_hmac("sha512", enc_key, mac_salt, 2, dklen=KEY_SZ)
    hmac_data = db_page1[SALT_SZ: PAGE_SZ - 80 + 16]
    stored_hmac = db_page1[PAGE_SZ - 64: PAGE_SZ]
    hm = hmac_mod.new(mac_key, hmac_data, hashlib.sha512)
    hm.update(struct.pack("<I", 1))
    return hm.digest() == stored_hmac


def collect_db_files(db_dir: str):
    """Walk db_dir and collect all .db files with their salts.

    Returns:
        (db_files, salt_to_dbs) where each db_files entry is
        ``(rel, path, size, salt_hex, page1)``.
    """
    db_files = []
    salt_to_dbs = {}
    if not db_dir or not os.path.isdir(db_dir):
        return db_files, salt_to_dbs
    for root, _dirs, files in os.walk(db_dir):
        for name in files:
            if not name.endswith(".db") or name.endswith("-wal") or name.endswith("-shm"):
                continue
            path = os.path.join(root, name)
            try:
                size = os.path.getsize(path)
            except OSError:
                continue
            if size < PAGE_SZ:
                continue
            try:
                with open(path, "rb") as f:
                    page1 = f.read(PAGE_SZ)
            except OSError:
                continue
            rel = os.path.relpath(path, db_dir)
            salt = page1[:SALT_SZ].hex()
            db_files.append((rel, path, size, salt, page1))
            salt_to_dbs.setdefault(salt, []).append(rel)
    return db_files, salt_to_dbs
