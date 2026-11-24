# -*- mode: python ; coding: utf-8 -*-
"""macOS .app bundle spec (onedir + BUNDLE).

Build:  ./quick_build_macos.sh
Output: dist/WeChat Export.app  and  dist/WeChatExport-*-macos-arm64.dmg
"""
import os
from pathlib import Path

ROOT = Path(SPECPATH).resolve()
SRC = ROOT / 'src'

datas = [
    (str(SRC), 'src'),
    (str(ROOT / 'README.md'), '.'),
]
docs_api = ROOT / 'docs' / 'HTTP-API.md'
if docs_api.is_file():
    datas.append((str(docs_api), 'docs'))

# Prefer a native silk_decoder if present; never ship Windows .exe on Mac.
silk = ROOT / 'tools' / 'silk_decoder'
if silk.is_file():
    datas.append((str(silk), 'tools'))
silk_c = ROOT / 'tools' / 'silk_decoder.c'
if silk_c.is_file():
    datas.append((str(silk_c), 'tools'))

hiddenimports = [
    'Crypto.Cipher.AES',
    'Crypto.Util.Padding',
    'flask',
    'werkzeug',
    'jinja2',
    'markdown',
    'blackboxprotobuf',
    'zstandard',
    'openpyxl',
    'jieba',
    'pypinyin',
    'psutil',
    'requests',
    'zhconv',
    'lameenc',
]

a = Analysis(
    [str(SRC / 'main.py')],
    pathex=[str(SRC)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['pytest', 'tkinter'],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='wechat_exp',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,  # keep a console so serve logs are visible
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='wechat_exp',
)

app = BUNDLE(
    coll,
    name='WeChat Export.app',
    icon=None,
    bundle_identifier='com.yuuu.wechat-export',
    info_plist={
        'CFBundleName': 'WeChat Export',
        'CFBundleDisplayName': 'WeChat Export',
        'CFBundleShortVersionString': '0.6.0',
        'CFBundleVersion': '2.16.20261124',
        'NSHighResolutionCapable': True,
        'LSMinimumSystemVersion': '12.0',
        'NSAppleEventsUsageDescription':
            'WeChat Export opens your browser to the local web UI.',
        # Analysis/export only — no auto key extract / SIP.
        'NSDocumentsFolderUsageDescription':
            '读取已解密备份或导出文件。',
    },
)
