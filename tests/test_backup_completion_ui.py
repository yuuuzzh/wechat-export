# -*- coding: utf-8 -*-
"""Backup/export completion UI regression guards."""
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(relative_path):
    return (ROOT / relative_path).read_text(encoding='utf-8')


def test_backup_page_first_run_range_and_completion_actions():
    template = _read('src/web/templates/backup.html')

    assert '<option value="30" selected>' in template
    assert "fetch('/api/workspace')" in template
    assert "daysSelect.value = hasBackup ? preferredDays : '0'" in template
    assert 'wechat-export-backup-days-pref' in template
    assert '首次建议备份全部；数据量大时可能较慢' in template
    assert 'href="/chat" class="btn btn-primary"' in template
    assert 'href="/export" class="btn btn-secondary"' in template
    assert 'href="/versions" class="btn btn-secondary"' in template
    assert "alert('检测失败" not in template


def test_wizard_download_result_has_theme_aware_next_steps():
    script = _read('src/web/static/js/wizard.js')

    assert "link.className = 'btn btn-primary'" in script
    assert "againButton.className = 'btn btn-secondary'" in script
    assert "againButton.textContent = '再导一份'" in script
    assert '文件路径：' in script
    assert '手动打开所在文件夹' in script
    assert "/api/util/open-path" in script
    assert "在文件夹中显示" in script
