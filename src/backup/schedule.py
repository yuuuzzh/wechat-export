# -*- coding: utf-8 -*-
"""Windows Task Scheduler helpers for daily incremental backup.

Creates a user-level scheduled task that runs ``backup`` (incremental by
default) once a day. Also writes a ``.bat`` runner and an importable ``.xml``
template under ``schedule/`` next to the exe / project root.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from typing import Any, Optional

DEFAULT_TASK_NAME = r'WeChatExport\DailyBackup'
DEFAULT_TIME = '02:00'
DEFAULT_DAYS = 0  # 0 = all history; incremental still reuses unchanged DBs/media


def schedule_root() -> str:
    """Directory for runner bat + XML template + logs."""
    if getattr(sys, 'frozen', False):
        base = os.path.dirname(sys.executable)
    else:
        base = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    root = os.path.join(base, 'schedule')
    os.makedirs(root, exist_ok=True)
    return root


def resolve_launcher() -> dict[str, Any]:
    """Find how to invoke ``backup`` on this machine."""
    if getattr(sys, 'frozen', False):
        exe = sys.executable
        return {
            'mode': 'frozen',
            'exe': exe,
            'cwd': os.path.dirname(exe),
            'argv_prefix': [exe, 'backup'],
        }
    # Dev: python src/main.py backup
    main_py = os.path.abspath(os.path.join(
        os.path.dirname(__file__), '..', 'main.py'))
    py = sys.executable
    return {
        'mode': 'source',
        'exe': py,
        'cwd': os.path.dirname(os.path.dirname(main_py)),
        'argv_prefix': [py, main_py, 'backup'],
        'main_py': main_py,
    }


def build_backup_argv(
    *,
    days: int = DEFAULT_DAYS,
    db_dir: Optional[str] = None,
    wxid: Optional[str] = None,
    full: bool = False,
    no_harvest: bool = True,
) -> list[str]:
    """CLI args after the launcher prefix (starts with ``backup`` already in prefix).

    Scheduled runs default to ``--no-harvest`` so they stay quiet without WeChat.
    """
    launcher = resolve_launcher()
    argv = list(launcher['argv_prefix'])
    argv += ['--days', str(int(days))]
    if db_dir:
        argv += ['--db-dir', db_dir]
    if wxid:
        argv += ['--wxid', wxid]
    if full:
        argv.append('--full')
    if no_harvest:
        argv.append('--no-harvest')
    return argv


def _quote_cmd(arg: str) -> str:
    if not arg:
        return '""'
    if re.search(r'[\s"&<>|^]', arg):
        return '"' + arg.replace('"', '""') + '"'
    return arg


def write_runner_bat(
    *,
    days: int = DEFAULT_DAYS,
    db_dir: Optional[str] = None,
    wxid: Optional[str] = None,
    full: bool = False,
) -> str:
    """Write ``schedule/daily_backup.bat`` and return its path."""
    root = schedule_root()
    bat = os.path.join(root, 'daily_backup.bat')
    log_dir = os.path.join(root, 'logs')
    os.makedirs(log_dir, exist_ok=True)
    launcher = resolve_launcher()
    argv = build_backup_argv(
        days=days, db_dir=db_dir, wxid=wxid, full=full, no_harvest=True,
    )
    cmdline = ' '.join(_quote_cmd(a) for a in argv)
    cwd = launcher['cwd']
    content = f'''@echo off
chcp 65001 >nul
setlocal
cd /d {_quote_cmd(cwd)}
set "LOGDIR={log_dir}"
if not exist "%LOGDIR%" mkdir "%LOGDIR%"
for /f %%I in ('powershell -NoProfile -Command "Get-Date -Format yyyy-MM-dd_HHmmss"') do set "STAMP=%%I"
set "LOG=%LOGDIR%\\backup_%STAMP%.log"
echo [%DATE% %TIME%] WeChat Export scheduled backup start>> "%LOG%"
echo Command: {cmdline}>> "%LOG%"
{cmdline} >> "%LOG%" 2>&1
set "EC=%ERRORLEVEL%"
echo [%DATE% %TIME%] exit=%EC%>> "%LOG%"
exit /b %EC%
'''
    with open(bat, 'w', encoding='utf-8', newline='\r\n') as f:
        f.write(content)
    return bat


def write_task_xml(
    *,
    bat_path: str,
    time_hhmm: str = DEFAULT_TIME,
    task_name: str = DEFAULT_TASK_NAME,
    author: str = 'WeChat Export',
) -> str:
    """Write Task Scheduler XML (for manual import) and return its path."""
    root = schedule_root()
    xml_path = os.path.join(root, 'WeChatExport_DailyBackup.xml')
    hh, mm = _parse_time(time_hhmm)
    # Task Scheduler wants local start boundary; use today's date + time
    today = datetime.now().strftime('%Y-%m-%d')
    start = f'{today}T{hh:02d}:{mm:02d}:00'
    # URI: last segment of task name
    uri = task_name.replace('\\', '/')
    bat_abs = os.path.abspath(bat_path)
    # XML schema for Task Scheduler 1.2
    xml = f'''<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo>
    <Date>{datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}</Date>
    <Author>{_xml_esc(author)}</Author>
    <URI>\\{_xml_esc(task_name)}</URI>
    <Description>WeChat Export daily incremental backup (auto-generated).</Description>
  </RegistrationInfo>
  <Triggers>
    <CalendarTrigger>
      <StartBoundary>{start}</StartBoundary>
      <Enabled>true</Enabled>
      <ScheduleByDay>
        <DaysInterval>1</DaysInterval>
      </ScheduleByDay>
    </CalendarTrigger>
  </Triggers>
  <Principals>
    <Principal id="Author">
      <LogonType>InteractiveToken</LogonType>
      <RunLevel>LeastPrivilege</RunLevel>
    </Principal>
  </Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <AllowHardTerminate>true</AllowHardTerminate>
    <StartWhenAvailable>true</StartWhenAvailable>
    <RunOnlyIfNetworkAvailable>false</RunOnlyIfNetworkAvailable>
    <IdleSettings>
      <StopOnIdleEnd>false</StopOnIdleEnd>
      <RestartOnIdle>false</RestartOnIdle>
    </IdleSettings>
    <AllowStartOnDemand>true</AllowStartOnDemand>
    <Enabled>true</Enabled>
    <Hidden>false</Hidden>
    <RunOnlyIfIdle>false</RunOnlyIfIdle>
    <WakeToRun>false</WakeToRun>
    <ExecutionTimeLimit>PT4H</ExecutionTimeLimit>
    <Priority>7</Priority>
  </Settings>
  <Actions Context="Author">
    <Exec>
      <Command>{_xml_esc(bat_abs)}</Command>
      <WorkingDirectory>{_xml_esc(os.path.dirname(bat_abs))}</WorkingDirectory>
    </Exec>
  </Actions>
</Task>
'''
    # Task Scheduler import prefers UTF-16 LE with BOM for encoding="UTF-16"
    with open(xml_path, 'w', encoding='utf-16', newline='\r\n') as f:
        f.write(xml)
    # Also keep a UTF-8 copy for humans / git
    utf8_path = os.path.join(root, 'WeChatExport_DailyBackup.utf8.xml')
    with open(utf8_path, 'w', encoding='utf-8', newline='\r\n') as f:
        f.write(xml.replace('encoding="UTF-16"', 'encoding="UTF-8"'))
    return xml_path


def _xml_esc(s: str) -> str:
    return (s or '').replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;').replace('"', '&quot;')


def _parse_time(time_hhmm: str) -> tuple[int, int]:
    m = re.match(r'^(\d{1,2}):(\d{2})$', (time_hhmm or '').strip())
    if not m:
        raise ValueError(f'时间格式应为 HH:MM，收到: {time_hhmm!r}')
    hh, mm = int(m.group(1)), int(m.group(2))
    if not (0 <= hh <= 23 and 0 <= mm <= 59):
        raise ValueError(f'无效时间: {time_hhmm}')
    return hh, mm


def _is_windows() -> bool:
    return os.name == 'nt'


def _run_schtasks(args: list[str], timeout: int = 60) -> subprocess.CompletedProcess:
    creationflags = 0
    if hasattr(subprocess, 'CREATE_NO_WINDOW'):
        creationflags = subprocess.CREATE_NO_WINDOW
    return subprocess.run(
        ['schtasks'] + args,
        capture_output=True,
        text=True,
        encoding='utf-8',
        errors='replace',
        timeout=timeout,
        creationflags=creationflags,
    )


def query_task(task_name: str = DEFAULT_TASK_NAME) -> dict[str, Any]:
    """Query whether the scheduled task exists."""
    if not _is_windows():
        return {
            'ok': True,
            'platform': sys.platform,
            'installed': False,
            'supported': False,
            'hint': '定时备份计划任务仅支持 Windows（仍可下载 bat/xml 模板）',
        }
    try:
        proc = _run_schtasks(['/Query', '/TN', task_name, '/FO', 'LIST', '/V'])
    except (OSError, subprocess.TimeoutExpired) as e:
        return {'ok': False, 'installed': False, 'supported': True, 'error': str(e)}
    out = (proc.stdout or '') + '\n' + (proc.stderr or '')
    if proc.returncode != 0:
        return {
            'ok': True,
            'supported': True,
            'installed': False,
            'task_name': task_name,
            'raw': out.strip()[:500],
        }
    info: dict[str, Any] = {
        'ok': True,
        'supported': True,
        'installed': True,
        'task_name': task_name,
    }
    for line in out.splitlines():
        if ':' not in line:
            continue
        k, _, v = line.partition(':')
        key = k.strip().lower()
        val = v.strip()
        if key in ('task name', '任务名', 'taskname'):
            info['reported_name'] = val
        elif key in ('status', '状态'):
            info['status'] = val
        elif key in ('next run time', '下次运行时间'):
            info['next_run'] = val
        elif key in ('last run time', '上次运行时间'):
            info['last_run'] = val
        elif key in ('last result', '上次结果'):
            info['last_result'] = val
        elif key in ('task to run', '要运行的任务', 'run'):
            info['task_to_run'] = val
        elif key in ('start time', '开始时间'):
            info['start_time'] = val
        elif key in ('schedule type', '计划类型'):
            info['schedule_type'] = val
    return info


def install_daily_task(
    *,
    time_hhmm: str = DEFAULT_TIME,
    days: int = DEFAULT_DAYS,
    db_dir: Optional[str] = None,
    wxid: Optional[str] = None,
    task_name: str = DEFAULT_TASK_NAME,
    full: bool = False,
) -> dict[str, Any]:
    """Write runner + XML and register a daily Task Scheduler job."""
    _parse_time(time_hhmm)  # validate early
    bat = write_runner_bat(days=days, db_dir=db_dir, wxid=wxid, full=full)
    xml_path = write_task_xml(bat_path=bat, time_hhmm=time_hhmm, task_name=task_name)
    hh, mm = _parse_time(time_hhmm)
    st = f'{hh:02d}:{mm:02d}'

    settings = {
        'enabled': True,
        'time': st,
        'days': int(days),
        'db_dir': db_dir or '',
        'wxid': wxid or '',
        'task_name': task_name,
        'full': bool(full),
        'bat_path': bat,
        'xml_path': xml_path,
        'updated_at': int(datetime.now().timestamp()),
    }
    save_schedule_settings(settings)

    if not _is_windows():
        return {
            'ok': True,
            'installed': False,
            'supported': False,
            'settings': settings,
            'hint': '非 Windows：已生成 bat/xml，请在目标机器上用「任务计划程序」导入 XML。',
        }

    # Prefer XML import (preserves settings); fall back to /SC DAILY
    proc = _run_schtasks(['/Create', '/TN', task_name, '/XML', xml_path, '/F'])
    if proc.returncode != 0:
        # Fallback: simple create with /TR
        tr = bat
        proc = _run_schtasks([
            '/Create', '/TN', task_name,
            '/TR', tr,
            '/SC', 'DAILY',
            '/ST', st,
            '/RL', 'LIMITED',
            '/F',
        ])
    if proc.returncode != 0:
        err = ((proc.stderr or '') + (proc.stdout or '')).strip()
        return {
            'ok': False,
            'installed': False,
            'supported': True,
            'error': err or f'schtasks exit {proc.returncode}',
            'settings': settings,
            'hint': '可手动打开「任务计划程序」→ 导入任务，选择已生成的 XML。',
            'xml_path': xml_path,
            'bat_path': bat,
        }

    q = query_task(task_name)
    return {
        'ok': True,
        'installed': True,
        'supported': True,
        'settings': settings,
        'task': q,
        'bat_path': bat,
        'xml_path': xml_path,
    }


def uninstall_task(task_name: str = DEFAULT_TASK_NAME) -> dict[str, Any]:
    settings = load_schedule_settings()
    settings['enabled'] = False
    settings['updated_at'] = int(datetime.now().timestamp())
    save_schedule_settings(settings)
    if not _is_windows():
        return {'ok': True, 'removed': False, 'hint': '非 Windows，仅更新了本地配置'}
    proc = _run_schtasks(['/Delete', '/TN', task_name, '/F'])
    if proc.returncode != 0:
        err = ((proc.stderr or '') + (proc.stdout or '')).strip()
        # "cannot find" is fine
        if 'cannot find' in err.lower() or '找不到' in err or 'ERROR: The system cannot find' in err:
            return {'ok': True, 'removed': False, 'missing': True, 'settings': settings}
        return {'ok': False, 'removed': False, 'error': err or f'exit {proc.returncode}'}
    return {'ok': True, 'removed': True, 'settings': settings}


def load_schedule_settings() -> dict[str, Any]:
    from engine.config_file import _config_path
    defaults = {
        'enabled': False,
        'time': DEFAULT_TIME,
        'days': DEFAULT_DAYS,
        'db_dir': '',
        'wxid': '',
        'task_name': DEFAULT_TASK_NAME,
        'full': False,
        'bat_path': '',
        'xml_path': '',
        'updated_at': 0,
    }
    path = _config_path()
    if not os.path.isfile(path):
        return defaults
    try:
        import json
        with open(path, 'r', encoding='utf-8') as f:
            cfg = json.load(f)
        saved = cfg.get('schedule_backup') or {}
        if isinstance(saved, dict):
            defaults.update({k: saved[k] for k in defaults if k in saved})
    except (ValueError, OSError):
        pass
    return defaults


def save_schedule_settings(settings: dict[str, Any]) -> dict[str, Any]:
    from engine.config_file import _config_path
    import json
    current = load_schedule_settings()
    current.update({k: v for k, v in (settings or {}).items() if k in current})
    path = _config_path()
    cfg: dict = {}
    try:
        if os.path.isfile(path):
            with open(path, 'r', encoding='utf-8') as f:
                cfg = json.load(f)
    except (ValueError, OSError):
        cfg = {}
    cfg['schedule_backup'] = current
    os.makedirs(os.path.dirname(path) or '.', exist_ok=True)
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)
    return current


def status_bundle() -> dict[str, Any]:
    """Combined UI payload: settings + task query + paths + launcher."""
    settings = load_schedule_settings()
    task_name = settings.get('task_name') or DEFAULT_TASK_NAME
    task = query_task(task_name)
    launcher = resolve_launcher()
    root = schedule_root()
    # Prefill db_dir from global config if empty
    if not settings.get('db_dir'):
        try:
            from engine.config_file import get_db_dir
            settings['db_dir'] = get_db_dir() or ''
        except Exception:
            pass
    if not settings.get('wxid'):
        try:
            from engine.config_file import get_backup_wxid
            settings['wxid'] = get_backup_wxid() or ''
        except Exception:
            pass
    return {
        'ok': True,
        'settings': settings,
        'task': task,
        'launcher': {
            'mode': launcher.get('mode'),
            'cwd': launcher.get('cwd'),
            'exe': launcher.get('exe'),
        },
        'paths': {
            'schedule_dir': root,
            'bat': os.path.join(root, 'daily_backup.bat'),
            'xml': os.path.join(root, 'WeChatExport_DailyBackup.xml'),
            'logs': os.path.join(root, 'logs'),
        },
        'argv_preview': build_backup_argv(
            days=int(settings.get('days') or 0),
            db_dir=settings.get('db_dir') or None,
            wxid=settings.get('wxid') or None,
            full=bool(settings.get('full')),
        ),
    }
