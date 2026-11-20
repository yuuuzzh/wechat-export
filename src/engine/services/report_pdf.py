# -*- coding: utf-8 -*-
"""Convert report HTML to PDF via Edge/Chrome headless (optional).

Falls back to None when no browser is available — UI can still use print dialog.
"""
from __future__ import annotations

import os
import shutil
import subprocess
from typing import Optional
from urllib.request import pathname2url


def _browser_candidates() -> list[str]:
    cands = []
    for name in (
        'msedge',
        'chrome',
        'google-chrome',
        'chromium',
        'chromium-browser',
    ):
        p = shutil.which(name)
        if p:
            cands.append(p)
    # Common Windows install paths
    local = os.environ.get('LOCALAPPDATA') or ''
    pf = os.environ.get('PROGRAMFILES') or r'C:\Program Files'
    pf86 = os.environ.get('PROGRAMFILES(X86)') or r'C:\Program Files (x86)'
    for path in (
        os.path.join(pf, 'Google', 'Chrome', 'Application', 'chrome.exe'),
        os.path.join(pf86, 'Google', 'Chrome', 'Application', 'chrome.exe'),
        os.path.join(pf, 'Microsoft', 'Edge', 'Application', 'msedge.exe'),
        os.path.join(pf86, 'Microsoft', 'Edge', 'Application', 'msedge.exe'),
        os.path.join(local, 'Google', 'Chrome', 'Application', 'chrome.exe'),
    ):
        if path and os.path.isfile(path):
            cands.append(path)
    # Dedupe
    seen = set()
    out = []
    for c in cands:
        ab = os.path.abspath(c)
        if ab not in seen:
            seen.add(ab)
            out.append(ab)
    return out


def html_file_to_pdf(html_path: str, pdf_path: Optional[str] = None) -> Optional[str]:
    """Print HTML file to PDF. Returns pdf path or None."""
    html_path = os.path.abspath(html_path)
    if not os.path.isfile(html_path):
        return None
    if not pdf_path:
        pdf_path = os.path.splitext(html_path)[0] + '.pdf'
    pdf_path = os.path.abspath(pdf_path)
    os.makedirs(os.path.dirname(pdf_path) or '.', exist_ok=True)

    file_url = 'file:///' + pathname2url(html_path.replace('\\', '/'))
    for browser in _browser_candidates():
        try:
            # Chrome/Edge: --print-to-pdf writes and exits
            cmd = [
                browser,
                '--headless=new',
                '--disable-gpu',
                '--no-pdf-header-footer',
                f'--print-to-pdf={pdf_path}',
                file_url,
            ]
            proc = subprocess.run(
                cmd,
                capture_output=True,
                timeout=120,
                check=False,
            )
            if os.path.isfile(pdf_path) and os.path.getsize(pdf_path) > 0:
                return pdf_path
            # Older flag
            cmd2 = [
                browser,
                '--headless',
                '--disable-gpu',
                f'--print-to-pdf={pdf_path}',
                file_url,
            ]
            subprocess.run(cmd2, capture_output=True, timeout=120, check=False)
            if os.path.isfile(pdf_path) and os.path.getsize(pdf_path) > 0:
                return pdf_path
        except (OSError, subprocess.TimeoutExpired):
            continue
    return None
