# -*- coding: utf-8 -*-
"""Scheduled backup: runner bat / XML template / schtasks wrappers."""
from __future__ import annotations

import os
import sys
from unittest import mock

import pytest

ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, os.path.join(ROOT, 'src'))

from backup import schedule as sch  # noqa: E402


def test_parse_time_and_argv(tmp_path, monkeypatch):
    monkeypatch.setattr(sch, 'schedule_root', lambda: str(tmp_path / 'schedule'))
    argv = sch.build_backup_argv(days=0, db_dir=r'D:\wx\db_storage', wxid='wxid_a')
    assert 'backup' in argv
    assert '--days' in argv and '0' in argv
    assert '--db-dir' in argv
    assert '--no-harvest' in argv
    assert '--full' not in argv

    with pytest.raises(ValueError):
        sch._parse_time('25:00')
    assert sch._parse_time('2:05') == (2, 5)


def test_write_bat_and_xml(tmp_path, monkeypatch):
    monkeypatch.setattr(sch, 'schedule_root', lambda: str(tmp_path / 'schedule'))
    monkeypatch.setattr(sch, 'resolve_launcher', lambda: {
        'mode': 'source',
        'exe': sys.executable,
        'cwd': str(tmp_path),
        'argv_prefix': [sys.executable, 'main.py', 'backup'],
    })
    bat = sch.write_runner_bat(days=30, db_dir=str(tmp_path / 'db'), wxid='wxid_t')
    assert os.path.isfile(bat)
    text = open(bat, encoding='utf-8').read()
    assert 'backup' in text
    assert '--days' in text
    assert '30' in text

    xml_path = sch.write_task_xml(bat_path=bat, time_hhmm='03:15')
    assert os.path.isfile(xml_path)
    raw = open(xml_path, encoding='utf-16').read()
    assert 'CalendarTrigger' in raw
    assert '03:15:00' in raw
    assert os.path.basename(bat) in raw or bat.replace('\\', '\\') in raw


def test_install_mocked_schtasks(tmp_path, monkeypatch):
    monkeypatch.setattr(sch, 'schedule_root', lambda: str(tmp_path / 'schedule'))
    monkeypatch.setattr(sch, '_is_windows', lambda: True)
    monkeypatch.setattr(sch, 'resolve_launcher', lambda: {
        'mode': 'frozen',
        'exe': str(tmp_path / 'wechat_exp.exe'),
        'cwd': str(tmp_path),
        'argv_prefix': [str(tmp_path / 'wechat_exp.exe'), 'backup'],
    })
    # Avoid touching real config path
    cfg = tmp_path / 'cfg.json'
    monkeypatch.setattr('engine.config_file._config_path', lambda: str(cfg))

    calls = []

    def fake_run(args, **kwargs):
        calls.append(args)
        class P:
            returncode = 0
            stdout = 'SUCCESS: The scheduled task "WeChatExport\\DailyBackup" has successfully been created.'
            stderr = ''
        return P()

    monkeypatch.setattr(sch, '_run_schtasks', fake_run)
    monkeypatch.setattr(sch, 'query_task', lambda name=None: {
        'ok': True, 'installed': True, 'supported': True, 'status': 'Ready',
    })

    result = sch.install_daily_task(
        time_hhmm='04:30', days=0, db_dir=str(tmp_path / 'db_storage'),
    )
    assert result['ok'] and result['installed']
    assert os.path.isfile(result['bat_path'])
    assert calls  # schtasks invoked
    assert cfg.is_file()


def test_api_status_and_template(tmp_path, monkeypatch):
    from web.app import create_app
    from engine import config_file as cf

    monkeypatch.setattr(cf, '_config_path', lambda: str(tmp_path / 'cfg.json'))
    monkeypatch.setattr(sch, 'schedule_root', lambda: str(tmp_path / 'schedule'))
    monkeypatch.setattr(sch, '_is_windows', lambda: False)

    app = create_app(decrypted_dir=str(tmp_path))
    cli = app.test_client()
    r = cli.get('/schedule')
    assert r.status_code == 200
    assert b'daily' in r.data.lower() or '增量'.encode() in r.data

    r = cli.get('/api/backup/schedule/status')
    j = r.get_json()
    assert j['ok']
    assert 'settings' in j

    r = cli.post('/api/backup/schedule/template', json={
        'time': '01:00', 'days': 0, 'db_dir': str(tmp_path / 'db'),
    })
    j = r.get_json()
    assert j['ok']
    assert os.path.isfile(j['bat_path'])
    assert os.path.isfile(j['xml_path'])

    r = cli.get('/api/backup/schedule/download/bat')
    assert r.status_code == 200
