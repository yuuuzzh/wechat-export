# -*- coding: utf-8 -*-
"""Scheduled backup API — Windows Task Scheduler daily incremental."""
from __future__ import annotations

import os

from flask import Blueprint, jsonify, request, send_file

schedule_bp = Blueprint('schedule_api', __name__, url_prefix='/api/backup/schedule')


@schedule_bp.route('/status', methods=['GET'])
def schedule_status():
    from backup.schedule import status_bundle
    return jsonify(status_bundle())


@schedule_bp.route('/install', methods=['POST'])
def schedule_install():
    """POST {time, days, db_dir?, wxid?, full?} — create daily incremental task."""
    from backup.schedule import install_daily_task
    from engine.config_file import get_db_dir, get_backup_wxid

    data = request.get_json(silent=True) or {}
    time_hhmm = (data.get('time') or '02:00').strip()
    try:
        days = int(data.get('days') if data.get('days') is not None else 0)
    except (TypeError, ValueError):
        return jsonify({'ok': False, 'error': 'days 必须是整数'}), 400
    db_dir = (data.get('db_dir') or get_db_dir() or '').strip()
    wxid = (data.get('wxid') or get_backup_wxid() or '').strip()
    full = bool(data.get('full'))

    if not db_dir and not wxid:
        return jsonify({
            'ok': False,
            'error': '请先在「一键备份 / 设置」中选定微信数据目录，或传入 db_dir / wxid，'
                     '否则无人值守任务无法选择账号。',
        }), 400

    try:
        result = install_daily_task(
            time_hhmm=time_hhmm,
            days=days,
            db_dir=db_dir or None,
            wxid=wxid or None,
            full=full,
        )
    except ValueError as e:
        return jsonify({'ok': False, 'error': str(e)}), 400
    status = 200 if result.get('ok') else 500
    return jsonify(result), status


@schedule_bp.route('/uninstall', methods=['POST'])
def schedule_uninstall():
    from backup.schedule import uninstall_task, load_schedule_settings
    data = request.get_json(silent=True) or {}
    settings = load_schedule_settings()
    name = (data.get('task_name') or settings.get('task_name') or '').strip()
    result = uninstall_task(name) if name else uninstall_task()
    status = 200 if result.get('ok') else 500
    return jsonify(result), status


@schedule_bp.route('/template', methods=['POST', 'GET'])
def schedule_template():
    """Generate bat + XML without registering the task; return paths."""
    from backup.schedule import (
        write_runner_bat, write_task_xml, load_schedule_settings, save_schedule_settings,
    )
    from engine.config_file import get_db_dir, get_backup_wxid

    data = request.get_json(silent=True) or {}
    settings = load_schedule_settings()
    time_hhmm = (data.get('time') or settings.get('time') or '02:00').strip()
    try:
        days = int(data.get('days') if data.get('days') is not None else settings.get('days') or 0)
    except (TypeError, ValueError):
        days = 0
    db_dir = (data.get('db_dir') or settings.get('db_dir') or get_db_dir() or '').strip()
    wxid = (data.get('wxid') or settings.get('wxid') or get_backup_wxid() or '').strip()
    full = bool(data.get('full') if 'full' in data else settings.get('full'))
    try:
        bat = write_runner_bat(days=days, db_dir=db_dir or None, wxid=wxid or None, full=full)
        xml_path = write_task_xml(bat_path=bat, time_hhmm=time_hhmm)
    except ValueError as e:
        return jsonify({'ok': False, 'error': str(e)}), 400
    save_schedule_settings({
        'time': time_hhmm,
        'days': days,
        'db_dir': db_dir,
        'wxid': wxid,
        'full': full,
        'bat_path': bat,
        'xml_path': xml_path,
    })
    return jsonify({
        'ok': True,
        'bat_path': bat,
        'xml_path': xml_path,
        'download_bat': '/api/backup/schedule/download/bat',
        'download_xml': '/api/backup/schedule/download/xml',
    })


@schedule_bp.route('/run-now', methods=['POST'])
def schedule_run_now():
    """POST — trigger the daily backup task / bat immediately."""
    from backup.schedule import run_task_now, load_schedule_settings
    data = request.get_json(silent=True) or {}
    settings = load_schedule_settings()
    name = (data.get('task_name') or settings.get('task_name') or '').strip() or None
    result = run_task_now(name)
    status = 200 if result.get('ok') else 500
    return jsonify(result), status


@schedule_bp.route('/download/<kind>', methods=['GET'])
def schedule_download(kind: str):
    from backup.schedule import schedule_root, write_runner_bat, write_task_xml, load_schedule_settings
    settings = load_schedule_settings()
    root = schedule_root()
    if kind == 'bat':
        path = settings.get('bat_path') or os.path.join(root, 'daily_backup.bat')
        if not os.path.isfile(path):
            path = write_runner_bat(
                days=int(settings.get('days') or 0),
                db_dir=settings.get('db_dir') or None,
                wxid=settings.get('wxid') or None,
                full=bool(settings.get('full')),
            )
        return send_file(path, as_attachment=True, download_name='daily_backup.bat')
    if kind == 'xml':
        path = settings.get('xml_path') or os.path.join(root, 'WeChatExport_DailyBackup.xml')
        if not os.path.isfile(path):
            bat = write_runner_bat(
                days=int(settings.get('days') or 0),
                db_dir=settings.get('db_dir') or None,
                wxid=settings.get('wxid') or None,
                full=bool(settings.get('full')),
            )
            path = write_task_xml(bat_path=bat, time_hhmm=settings.get('time') or '02:00')
        return send_file(path, as_attachment=True, download_name='WeChatExport_DailyBackup.xml')
    return jsonify({'error': 'kind 仅支持 bat / xml'}), 400
