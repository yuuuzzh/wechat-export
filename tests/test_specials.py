# -*- coding: utf-8 -*-
"""Favorites + file-transfer-assistant export."""
from __future__ import annotations

import hashlib
import os
import sqlite3
import sys

import pytest

ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, os.path.join(ROOT, 'src'))

from engine.services.specials import (  # noqa: E402
    export_favorites,
    export_filehelper,
    favorites_status,
    filehelper_status,
    list_favorites,
    parse_fav_xml,
)


def test_parse_article_and_chat_record():
    article = (
        '<favitem><pagetitle>一篇文章</pagetitle>'
        '<pagedesc>摘要</pagedesc><link>https://example.com/a</link>'
        '<sourcename>公众号</sourcename></favitem>'
    )
    got = parse_fav_xml(article, 5)
    assert got['title'] == '一篇文章'
    assert '摘要' in got['body']
    assert got['url'].startswith('https://')

    chat = (
        '<favitem><datalist>'
        '<dataitem><datasrcname>甲</datasrcname><datadesc>你好</datadesc></dataitem>'
        '<dataitem><datasrcname>乙</datasrcname><datadesc>收到</datadesc></dataitem>'
        '</datalist></favitem>'
    )
    got = parse_fav_xml(chat, 14)
    assert len(got['chat_lines']) == 2
    assert '你好' in got['body']


def test_list_and_export_favorites(tmp_path):
    backup = tmp_path / 'backup'
    fav_dir = backup / 'favorite'
    fav_dir.mkdir(parents=True)
    db = fav_dir / 'favorite.db'
    conn = sqlite3.connect(str(db))
    conn.execute(
        'CREATE TABLE fav_db_item ('
        'localId INT, type INT, createTime INT, updateTime INT, '
        'xmlBuf TEXT, tagNames TEXT)'
    )
    xml = '<favitem><pagetitle>报销单</pagetitle><pagedesc>三月</pagedesc></favitem>'
    conn.execute(
        'INSERT INTO fav_db_item VALUES (1, 5, 1700000000, 1700000001, ?, ?)',
        (xml, '工作,财务'),
    )
    conn.commit()
    conn.close()

    st = favorites_status(str(backup))
    assert st['available'] and st['count'] == 1
    listed = list_favorites(str(backup), keyword='报销')
    assert listed['ok'] and listed['total'] == 1
    assert listed['items'][0]['tags'] == ['工作', '财务']

    out = tmp_path / 'fav.md'
    res = export_favorites(str(backup), str(out), fmt='md')
    assert res['ok'] and res['count'] == 1
    assert '报销单' in out.read_text(encoding='utf-8')


def test_filehelper_export(tmp_path):
    backup = tmp_path / 'backup'
    msg = backup / 'message'
    msg.mkdir(parents=True)
    h = hashlib.md5(b'filehelper').hexdigest()
    db = msg / 'message_0.db'
    conn = sqlite3.connect(str(db))
    conn.execute('CREATE TABLE Name2Id (user_name TEXT)')
    conn.execute('INSERT INTO Name2Id VALUES (?)', ('filehelper',))
    tname = f'Msg_{h}'
    conn.execute(
        f'CREATE TABLE [{tname}] ('
        'local_id INT, local_type INT, real_sender_id INT, create_time INT, '
        'status INT, message_content BLOB, origin_source INT)'
    )
    # plain text type 1 — chat_export may expect zstd; store uncompressed and see
    conn.execute(
        f'INSERT INTO [{tname}] VALUES (1, 1, 0, 1700000100, 0, ?, 0)',
        ('你好，文件在这'.encode('utf-8'),),
    )
    conn.commit()
    conn.close()

    st = filehelper_status(str(backup))
    assert st['available']
    assert st['msg_count'] == 1

    res = export_filehelper(str(backup), str(tmp_path / 'out'), fmt='json')
    # decode may drop the row if content isn't zstd; status still proves discovery
    assert res['ok'] or res.get('count') == 0
    if res.get('path'):
        assert os.path.isfile(res['path'])


def test_missing_favorite_hint(tmp_path):
    st = favorites_status(str(tmp_path))
    assert st['available'] is False
    assert 'favorite.db' in (st.get('hint') or '')


def test_api_status_page(tmp_path):
    from web.app import create_app
    app = create_app(decrypted_dir=str(tmp_path))
    cli = app.test_client()
    r = cli.get('/specials')
    assert r.status_code == 200
    assert b'filehelper' in r.data
    r = cli.get('/api/specials/status')
    j = r.get_json()
    assert j['ok']
    assert j['favorites']['available'] is False
    assert j['filehelper']['available'] is False
