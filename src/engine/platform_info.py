# -*- coding: utf-8 -*-
"""Runtime platform capabilities for WeChat Export.

TraceMemo can ship macOS because it bundles native WCDB + key helpers.
WeChat Export's analysis/export core is portable Python; the hard blockers
are Win32 process-memory key extraction and Windows packaging. This module
exposes what the current host can do so the UI/CLI can degrade gracefully.
"""
from __future__ import annotations

import os
import platform
import shutil
import sys
from typing import Any


def is_windows() -> bool:
    return sys.platform.startswith('win')


def is_macos() -> bool:
    return sys.platform == 'darwin'


def is_linux() -> bool:
    return sys.platform.startswith('linux')


def is_macos_app_bundle(executable: str | None = None) -> bool:
    """True when the frozen binary lives inside ``Something.app/Contents/MacOS``."""
    exe = os.path.abspath(executable or sys.executable)
    macos_dir = os.path.dirname(exe)
    if os.path.basename(macos_dir) != 'MacOS':
        return False
    contents = os.path.dirname(macos_dir)
    if os.path.basename(contents) != 'Contents':
        return False
    return os.path.dirname(contents).endswith('.app')


def frozen_data_root(executable: str | None = None) -> str:
    """Writable data root for frozen builds.

    - Windows / bare onedir: directory containing the executable
    - macOS ``.app``: ``~/Library/Application Support/WeChatExport``
      (``/Applications`` is not writable for backups/config)
    """
    if not getattr(sys, 'frozen', False) and executable is None:
        # Allow unit tests to pass an explicit path without freezing.
        pass
    exe = os.path.abspath(executable or sys.executable)
    exe_dir = os.path.dirname(exe)
    if is_macos() and is_macos_app_bundle(exe):
        support = os.path.join(
            os.path.expanduser('~'),
            'Library', 'Application Support', 'WeChatExport',
        )
        os.makedirs(support, exist_ok=True)
        return support
    return exe_dir


def data_root() -> str:
    """Project/data root: repo root in source mode, :func:`frozen_data_root` when frozen."""
    if getattr(sys, 'frozen', False):
        return frozen_data_root()
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.normpath(os.path.join(here, '..', '..'))


def system_name() -> str:
    if is_windows():
        return 'windows'
    if is_macos():
        return 'macos'
    if is_linux():
        return 'linux'
    return sys.platform or 'unknown'


def auto_key_extract_supported() -> bool:
    """Built-in, zero-setup auto extract (Config.Cipher) is Windows-only.

    NOTE: macOS providers live in ``engine.services.mac_key`` and are reported
    separately by :func:`mac_key_capabilities`. This flag deliberately stays
    False on macOS so the first-run wizard keeps steering ordinary users to
    manual keys / decrypted backups until a first-party helper ships.
    """
    return is_windows()


def mac_auto_key_ready(db_dir: str = '') -> bool:
    """True when a TraceMemo-style helper is installed and can be invoked.

    Intentionally separate from :func:`auto_key_extract_supported`: the latter
    gates the Win32 ``key_scan`` path in ``backup/pipeline.py`` and must stay
    Windows-only. UI surfaces use this flag to expose the Mac advanced mode.
    """
    return bool(mac_key_capabilities(db_dir).get('auto_extract_ready'))


def mac_key_capabilities(db_dir: str = '') -> dict[str, Any]:
    """Read-only snapshot of the macOS key-source layer.

    Safe to call on every platform; on non-macOS hosts it returns a minimal
    ``{'enabled': False}`` dict without running any external command.
    """
    if not is_macos():
        return {'enabled': False, 'reason': 'not_macos',
                'auto_extract_ready': False, 'providers': []}
    try:
        from engine.services.mac_key import diagnostics
        info = diagnostics.collect(db_dir)
        return {
            'enabled': True,
            'auto_extract_ready': bool(info.get('auto_extract_ready')),
            'capture_ready': bool(info.get('capture_ready')),
            'mac_key_flow': info.get('mac_key_flow', ''),
            'sip_enabled': info.get('sip_enabled'),
            'wechat_running': info.get('wechat_running'),
            'wechat_version': info.get('wechat_version', ''),
            'helper_mode': info.get('helper_mode', ''),
            'helper_inventory': info.get('helper_inventory', {}),
            'mmkv_layout': info.get('mmkv', {}).get('layout', 'none'),
            'providers': info.get('providers', []),
        }
    except Exception as exc:  # diagnostics must never break /api/health
        return {'enabled': True, 'auto_extract_ready': False,
                'error': str(exc)[:160], 'providers': []}


def v2_key_harvest_supported() -> bool:
    return is_windows()


def task_scheduler_supported() -> bool:
    """Windows Task Scheduler templates; macOS launchd not implemented yet."""
    return is_windows()


def ffmpeg_install_zip_supported() -> bool:
    """One-click Windows ZIP install; Mac users should use brew."""
    return is_windows()


def find_ffmpeg() -> str:
    found = shutil.which('ffmpeg')
    if found:
        return found
    # Also accept tools/ffmpeg(.exe) — media module has richer search.
    try:
        from engine.services.media import _find_ffmpeg
        return _find_ffmpeg() or ''
    except Exception:
        return ''


def find_silk_decoder() -> str:
    try:
        from engine.services.media import _find_silk_decoder
        return _find_silk_decoder() or ''
    except Exception:
        return ''


def open_path(path: str) -> bool:
    """Open a folder/file with the OS file manager. Cross-platform."""
    if not path or not os.path.exists(path):
        return False
    try:
        if is_windows():
            os.startfile(path)  # type: ignore[attr-defined]
            return True
        if is_macos():
            import subprocess
            subprocess.Popen(['open', path])
            return True
        import subprocess
        subprocess.Popen(['xdg-open', path])
        return True
    except Exception:
        return False


def mac_wechat_roots() -> list[str]:
    """Candidate Mac WeChat data roots (sandbox + Application Support)."""
    home = os.path.expanduser('~')
    roots = [
        os.path.join(
            home, 'Library', 'Containers', 'com.tencent.xinWeChat',
            'Data', 'Documents', 'xwechat_files'),
        os.path.join(
            home, 'Library', 'Containers', 'com.tencent.xinWeChat',
            'Data', 'Library', 'Application Support',
            'com.tencent.xinWeChat', 'xwechat_files'),
        os.path.join(
            home, 'Library', 'Application Support',
            'com.tencent.xinWeChat', 'xwechat_files'),
        os.path.join(home, 'Documents', 'xwechat_files'),
    ]
    return [p for p in roots if p]


def capabilities() -> dict[str, Any]:
    """Snapshot for /api/health and UI banners."""
    return {
        'system': system_name(),
        'python': platform.python_version(),
        'machine': platform.machine(),
        'auto_key_extract': auto_key_extract_supported(),
        'mac_key': mac_key_capabilities(),
        'v2_key_harvest': v2_key_harvest_supported(),
        'task_scheduler': task_scheduler_supported(),
        'ffmpeg_zip_install': ffmpeg_install_zip_supported(),
        'ffmpeg': bool(find_ffmpeg()),
        'silk_decoder': bool(find_silk_decoder()),
        'manual_keys': True,
        'decrypted_viewer': True,
        'notes': _platform_notes(),
    }


def _platform_notes() -> list[str]:
    notes = []
    if is_macos():
        notes.append(
            'macOS：默认走「手动输入密钥」或已解密备份。高级模式参考 TraceMemo，'
            '需自备 xkey_helper、临时关闭 SIP 并完成管理员授权，'
            '且微信停在登录页；详见 docs/mac-auto-key.md。'
        )
        notes.append(
            '建议：brew install ffmpeg；语音 SILK 解码需自行编译 tools/silk_decoder。'
        )
        notes.append(
            '可用 quick_build_macos.sh 打出 WeChat Export.app / .dmg（未公证；'
            '首次打开请右键 → 打开）。'
        )
    elif is_linux():
        notes.append(
            'Linux：无微信官方桌面客户端密钥提取；可打开已解密备份或手动导入密钥。'
        )
    elif is_windows():
        notes.append('Windows：支持一键备份、自动密钥提取与计划任务。')
    return notes
