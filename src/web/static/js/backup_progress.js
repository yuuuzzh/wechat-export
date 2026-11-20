/* backup_progress.js — Global backup job chip + page resume helper */
(function () {
  const STORAGE_KEY = 'wechat-export-backup-job';
  const POLL_MS = 2500;

  function esc(s) {
    const d = document.createElement('div');
    d.textContent = s == null ? '' : String(s);
    return d.innerHTML;
  }

  function ensureChip() {
    let chip = document.getElementById('backup-job-chip');
    if (chip) return chip;
    chip = document.createElement('a');
    chip.id = 'backup-job-chip';
    chip.className = 'backup-job-chip';
    chip.href = '/backup';
    chip.style.display = 'none';
    chip.setAttribute('aria-live', 'polite');
    const nav = document.getElementById('top-nav');
    const right = nav && nav.querySelector('.nav-right');
    if (right) {
      right.insertBefore(chip, right.firstChild);
    } else if (nav) {
      nav.appendChild(chip);
    } else {
      document.body.appendChild(chip);
    }
    return chip;
  }

  function renderChip(job) {
    const chip = ensureChip();
    const onBackupPage = /^\/backup\/?$/.test(location.pathname);
    if (!job || !job.running) {
      chip.style.display = 'none';
      chip.innerHTML = '';
      return;
    }
    // On the backup page the full progress panel is enough.
    if (onBackupPage) {
      chip.style.display = 'none';
      return;
    }
    const pct = Math.max(0, Math.min(100, Math.round((job.progress || 0) * 100)));
    chip.style.display = 'inline-flex';
    chip.title = '备份在后台进行中，点击查看详情';
    chip.innerHTML =
      '<span class="backup-job-chip-label">备份中</span>' +
      '<span class="backup-job-chip-bar"><span style="width:' + pct + '%"></span></span>' +
      '<span class="backup-job-chip-pct">' + pct + '%</span>';
  }

  async function fetchJob() {
    try {
      const res = await fetch('/api/backup/job', { headers: { Accept: 'application/json' } });
      if (!res.ok) return null;
      const data = await res.json();
      return data && data.job ? data.job : null;
    } catch (e) {
      return null;
    }
  }

  async function tick() {
    const job = await fetchJob();
    if (job && job.id) {
      try { sessionStorage.setItem(STORAGE_KEY, job.id); } catch (e) { /* ignore */ }
    } else {
      try { sessionStorage.removeItem(STORAGE_KEY); } catch (e) { /* ignore */ }
    }
    renderChip(job);
    return job;
  }

  /**
   * Used by backup.html: if a job is still running (or just finished),
   * restore the progress panel and reattach SSE.
   */
  window.resumeBackupJobIfAny = async function resumeBackupJobIfAny(page) {
    if (!page) return null;
    const job = await fetchJob();
    if (!job) return null;
    if (job.id) page.rememberJobId(job.id);

    if (job.running) {
      page.runBtn.disabled = true;
      page.progressContainer.style.display = 'block';
      page.resultContainer.style.display = 'none';
      page.updateProgress(job.progress || 0, job.detail || '备份进行中…');
      if (job.stage) page.setActiveStep(job.stage);
      if (job.logs && job.logs.length && page.logConsole && !page.logConsole.children.length) {
        for (const line of job.logs.slice(-40)) {
          page.appendLog(line.detail || '', line.stage === 'error' ? 'error' : 'ok');
        }
      }
      page.attachJob('/api/backup/job/' + encodeURIComponent(job.id) + '/events');
      return job;
    }

    if (job.status === 'done' && job.result) {
      page.progressContainer.style.display = 'block';
      page.updateProgress(1, '完成');
      page.handleDone({ result: job.result, job_id: job.id });
      return job;
    }
    if (job.status === 'error' && job.error) {
      page.progressContainer.style.display = 'block';
      page.handleError(new Error(job.error));
      return job;
    }
    return job;
  };

  window.BackupJobChip = { tick: tick, STORAGE_KEY: STORAGE_KEY, esc: esc };

  // Auto-start lightweight polling on every page.
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', function () {
      tick();
      setInterval(tick, POLL_MS);
    });
  } else {
    tick();
    setInterval(tick, POLL_MS);
  }
})();
