# -*- coding: utf-8 -*-
"""ASR transcripts merged into search FTS."""
from __future__ import annotations

import os
import sqlite3
import sys
import tempfile

ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, os.path.join(ROOT, 'src'))

from engine.services import search_index as si  # noqa: E402
from engine.services.asr_store import AsrStore  # noqa: E402
from engine.services.search_query import to_char_token_text  # noqa: E402


def _mini_index(path):
    conn = sqlite3.connect(path)
    conn.executescript("""
CREATE TABLE msg_meta (
  chat_id TEXT NOT NULL,
  local_id INTEGER NOT NULL,
  create_time INTEGER NOT NULL,
  local_type INTEGER,
  sender_username TEXT,
  db_stem TEXT,
  PRIMARY KEY (chat_id, local_id, create_time)
) WITHOUT ROWID;
""")
    si._ensure_text_table(conn)
    si._create_fts_table(conn)
    # voice message with empty wechat text — only in meta
    conn.execute(
        'INSERT INTO msg_meta VALUES (?,?,?,?,?,?)',
        ('wxid_a', 7, 1700000000, 34, 'wxid_a', 'message_0'),
    )
    # text message already in fts
    conn.execute(
        'INSERT INTO msg_meta VALUES (?,?,?,?,?,?)',
        ('wxid_a', 8, 1700000100, 1, 'wxid_a', 'message_0'),
    )
    conn.execute(
        'INSERT INTO msg_text(rowid, chat_id, local_id, create_time, raw_text) VALUES (1,?,?,?,?)',
        ('wxid_a', 8, 1700000100, '你好'),
    )
    tok = to_char_token_text('你好')
    conn.execute(
        'INSERT INTO message_fts(rowid, text, chat_id, local_id, create_time) VALUES (1,?,?,?,?)',
        (tok, 'wxid_a', 8, 1700000100),
    )
    conn.commit()
    return conn


def test_merge_asr_raw_idempotent():
    a = si._merge_asr_raw('', '明天见')
    assert a.startswith(si.ASR_PREFIX) and '明天见' in a
    b = si._merge_asr_raw(a, '明天见')
    assert b == a
    c = si._merge_asr_raw('文字聊', '语音内容')
    assert '文字聊' in c and si.ASR_PREFIX in c and '语音内容' in c


def test_upsert_insert_and_update():
    fd, path = tempfile.mkstemp(suffix='.db')
    os.close(fd)
    try:
        conn = _mini_index(path)
        # Insert ASR for empty voice
        assert si._upsert_asr_row(conn, 'wxid_a', 7, 1700000000, '开会改到三点') == 'inserted'
        row = conn.execute(
            'SELECT raw_text FROM msg_text WHERE chat_id=? AND local_id=? AND create_time=?',
            ('wxid_a', 7, 1700000000),
        ).fetchone()
        assert row and '开会改到三点' in row[0]
        # FTS match
        hits = conn.execute(
            "SELECT chat_id FROM message_fts WHERE message_fts MATCH ?",
            (to_char_token_text('开会'),),
        ).fetchall()
        assert hits
        assert si._upsert_asr_row(conn, 'wxid_a', 7, 1700000000, '开会改到三点') == 'same'
        # Append ASR onto existing text message
        assert si._upsert_asr_row(conn, 'wxid_a', 8, 1700000100, '补充语音') == 'updated'
        raw = conn.execute('SELECT raw_text FROM msg_text WHERE rowid=1').fetchone()[0]
        assert '你好' in raw and '补充语音' in raw
        conn.close()
    finally:
        try:
            os.remove(path)
        except OSError:
            pass


def test_list_for_fts(tmp_path):
    db = str(tmp_path / 't.db')
    st = AsrStore(db)
    st.put('h1', 'hello voice', chat_id='c1', create_time=1, local_id=2)
    st.put('h2', '', chat_id='c1', create_time=3, local_id=4)  # ignored empty
    rows = st.list_for_fts()
    st.close()
    assert len(rows) == 1
    assert rows[0]['text'] == 'hello voice'
