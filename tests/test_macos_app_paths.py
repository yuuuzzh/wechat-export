# -*- coding: utf-8 -*-
"""macOS .app writable-root helpers."""
from pathlib import Path

from engine.platform_info import is_macos_app_bundle, frozen_data_root


def test_is_macos_app_bundle_detection(tmp_path: Path):
    exe = tmp_path / 'WeChat Export.app' / 'Contents' / 'MacOS' / 'wechat_exp'
    exe.parent.mkdir(parents=True)
    exe.write_text('x', encoding='utf-8')
    assert is_macos_app_bundle(str(exe)) is True
    bare = tmp_path / 'wechat_exp'
    bare.write_text('x', encoding='utf-8')
    assert is_macos_app_bundle(str(bare)) is False


def test_frozen_data_root_for_app_uses_application_support(tmp_path: Path, monkeypatch):
    import engine.platform_info as pi

    exe = tmp_path / 'WeChat Export.app' / 'Contents' / 'MacOS' / 'wechat_exp'
    exe.parent.mkdir(parents=True)
    exe.write_text('x', encoding='utf-8')
    fake_home = tmp_path / 'home'
    fake_home.mkdir()
    monkeypatch.setenv('HOME', str(fake_home))
    monkeypatch.setattr(pi, 'is_macos', lambda: True)
    root = frozen_data_root(str(exe))
    assert root == str(fake_home / 'Library' / 'Application Support' / 'WeChatExport')
    assert Path(root).is_dir()


def test_macos_build_assets_present():
    root = Path(__file__).resolve().parents[1]
    assert (root / 'wechat_exp_macos.spec').is_file()
    assert (root / 'quick_build_macos.sh').is_file()
    spec = (root / 'wechat_exp_macos.spec').read_text(encoding='utf-8')
    assert 'WeChat Export.app' in spec
    assert 'BUNDLE' in spec
    sh = (root / 'quick_build_macos.sh').read_text(encoding='utf-8')
    assert 'hdiutil' in sh
    assert 'codesign' in sh
