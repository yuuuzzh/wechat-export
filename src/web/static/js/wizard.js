/* wizard.js — Shared wizard page logic (config → SSE → result) */
class WizardPage {
  constructor(options) {
    this.formId = options.formId || 'wizard-form';
    this.runBtnId = options.runBtnId || 'btn-run';
    this.progressContainerId = options.progressContainerId || 'progress-container';
    this.resultContainerId = options.resultContainerId || 'result-container';
    this.logContainerId = options.logContainerId || 'log-console';
    this.progressBarId = options.progressBarId || 'progress-bar';
    this.progressDetailId = options.progressDetailId || 'progress-detail';
    this.steps = options.steps || [];
    this.apiUrl = options.apiUrl || '';
    this.method = options.method || 'POST';
    this.getBody = options.getBody || (() => ({}));
    this.chatFieldId = options.chatFieldId || 'cfg-chat';
    this.detailFormatter = options.detailFormatter || null;

    this.form = document.getElementById(this.formId);
    this.runBtn = document.getElementById(this.runBtnId);
    this.progressContainer = document.getElementById(this.progressContainerId);
    this.resultContainer = document.getElementById(this.resultContainerId);
    this.logConsole = document.getElementById(this.logContainerId);
    this.progressBar = document.getElementById(this.progressBarId);
    this.progressDetail = document.getElementById(this.progressDetailId);

    this.sse = null;
    this.currentStage = '';
    this._selectedDisplayName = '';
    this.jobId = null;
    this.jobStorageKey = options.jobStorageKey || '';
    this.bindEvents();
  }

  bindEvents() {
    if (this.runBtn) {
      this.runBtn.addEventListener('click', () => this.start());
    }
  }

  start() {
    this.runBtn.disabled = true;
    this.progressContainer.style.display = 'block';
    this.resultContainer.style.display = 'none';
    const selectContainer = document.getElementById('select-container');
    if (selectContainer) selectContainer.style.display = 'none';
    this.logConsole.innerHTML = '';
    this.updateProgress(0, '正在准备...');

    const body = this.getBody();
    if (this._selectedDisplayName) {
      body.display_name = this._selectedDisplayName;
      this._selectedDisplayName = '';
    }

    if (this.sse) this.sse.stop();
    this.sse = new SseProgress(this.apiUrl, {
      method: this.method,
      body: body,
      onProgress: (data) => this.handleProgress(data),
      onDone: (data) => this.handleDone(data),
      onError: (err) => this.handleError(err),
      onSelect: (data) => this.handleSelect(data),
    });
    this.sse.start();
  }

  rememberJobId(jobId) {
    if (!jobId) return;
    this.jobId = jobId;
    if (this.jobStorageKey) {
      try { sessionStorage.setItem(this.jobStorageKey, jobId); } catch (e) { /* ignore */ }
    }
  }

  clearJobId() {
    this.jobId = null;
    if (this.jobStorageKey) {
      try { sessionStorage.removeItem(this.jobStorageKey); } catch (e) { /* ignore */ }
    }
  }

  handleProgress(data) {
    if (data && data.job_id) this.rememberJobId(data.job_id);
    const detail = this.formatDetail(data && data.stage, (data && data.detail) || '');
    if (data && data.replay) {
      // Replayed history: update bar/stage, skip flooding the log console.
      this.updateProgress(data.progress || 0, detail);
      if (data.stage && data.stage !== this.currentStage) {
        this.currentStage = data.stage;
        this.setActiveStep(data.stage);
      }
      return;
    }
    this.updateProgress(data.progress || 0, detail);
    if (data.stage && data.stage !== this.currentStage) {
      this.currentStage = data.stage;
      this.setActiveStep(data.stage);
    }
    const cls = data.stage === 'error' ? 'error' : 'ok';
    this.appendLog(detail, cls);
  }

  handleDone(data) {
    if (data && data.job_id) this.rememberJobId(data.job_id);
    this.updateProgress(1.0, '完成');
    const result = data.result || data;
    const hasErrors = result && result.errors && result.errors.length > 0;
    if (hasErrors) {
      this.appendLog('✗ 操作失败: ' + result.errors.join('; '), 'error');
    } else {
      this.appendLog('✓ 操作完成', 'ok');
    }
    this.showResult(result);
    this.runBtn.disabled = false;
    this.markAllStepsDone();
    this.clearJobId();
  }

  handleError(err) {
    this.appendLog('✗ ' + err.message, 'error');
    this.runBtn.disabled = false;
    this.clearJobId();
  }

  /**
   * Reattach to an existing async job (e.g. backup still running after nav away).
   * @param {string} eventsUrl SSE endpoint for the job
   */
  attachJob(eventsUrl) {
    if (!eventsUrl) return;
    this.runBtn.disabled = true;
    this.progressContainer.style.display = 'block';
    this.resultContainer.style.display = 'none';
    if (this.sse) this.sse.stop();
    this.sse = new SseProgress(eventsUrl, {
      method: 'GET',
      body: null,
      onProgress: (data) => this.handleProgress(data),
      onDone: (data) => this.handleDone(data),
      onError: (err) => this.handleError(err),
      onSelect: (data) => this.handleSelect(data),
    });
    this.sse.start();
  }

  handleSelect(data) {
    this.runBtn.disabled = false;
    this.progressContainer.style.display = 'none';
    const matches = data.matches || [];
    this.showSelectDialog(matches);
  }

  showSelectDialog(matches) {
    const container = document.getElementById('select-container');
    if (!container) return;
    let html = '<h3 style="margin:0 0 12px 0;color:#e94560">请选择聊天对象</h3>';
    html += '<div class="select-list">';
    for (const m of matches) {
      const name = this.escapeHtml(m.display_name || m.username);
      const count = (m.msg_count || 0).toLocaleString();
      html += '<div class="select-item" data-username="' + this.escapeHtml(m.username) + '" data-display-name="' + this.escapeHtml(m.display_name || m.username) + '">';
      html += '<span class="select-name">' + name + '</span>';
      html += '<span class="select-count">' + count + ' 条消息</span>';
      html += '</div>';
    }
    html += '</div>';
    container.innerHTML = html;
    container.style.display = 'block';

    for (const item of container.querySelectorAll('.select-item')) {
      item.addEventListener('click', () => {
        const username = item.dataset.username;
        this._selectedDisplayName = item.dataset.displayName || '';
        container.style.display = 'none';
        const chatField = document.getElementById(this.chatFieldId);
        if (chatField) chatField.value = username;
        this.start();
      });
    }
  }

  escapeHtml(str) {
    const div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
  }

  formatDetail(stage, detail) {
    if (!this.detailFormatter) return detail;
    try {
      return this.detailFormatter(stage || '', detail);
    } catch (e) {
      return detail;
    }
  }

  updateProgress(pct, detail) {
    this.progressBar.style.width = (pct * 100).toFixed(0) + '%';
    this.progressDetail.textContent = detail;
  }

  appendLog(msg, cls) {
    const div = document.createElement('div');
    div.className = 'log-line ' + (cls || '');
    div.textContent = msg;
    this.logConsole.appendChild(div);
    this.logConsole.scrollTop = this.logConsole.scrollHeight;
  }

  setActiveStep(stage) {
    for (const item of document.querySelectorAll('.step-item')) {
      item.classList.remove('active');
      if (item.dataset.stage === stage) {
        item.classList.add('active');
      }
    }
  }

  markAllStepsDone() {
    for (const item of document.querySelectorAll('.step-item')) {
      item.classList.add('done');
    }
  }

  showResult(result) {
    this.resultContainer.style.display = 'block';
    const container = document.getElementById('result-content');
    if (!container) return;
    container.innerHTML = '';

    if (!result) return;

    const appendSummary = (text) => {
      const summary = document.createElement('p');
      summary.style.cssText = 'color:var(--px-muted);margin:0 0 8px 0';
      summary.textContent = text;
      container.appendChild(summary);
    };
    const appendPath = (path, manualHint) => {
      const pathLabel = document.createElement('p');
      pathLabel.style.cssText = 'color:var(--px-muted);margin:10px 0 0 0;line-height:1.7';
      pathLabel.appendChild(document.createTextNode('文件路径：'));
      const code = document.createElement('code');
      code.style.cssText = 'font-family:monospace;word-break:break-all';
      code.textContent = path;
      pathLabel.appendChild(code);
      container.appendChild(pathLabel);
      if (manualHint) {
        const hint = document.createElement('p');
        hint.style.cssText = 'color:var(--px-muted);font-size:12px;margin:4px 0 0 0';
        hint.textContent = '请复制以上路径，在文件管理器中手动打开所在文件夹。';
        container.appendChild(hint);
      }
    };
    const createActions = () => {
      const actions = document.createElement('div');
      actions.style.cssText = 'display:flex;gap:10px;flex-wrap:wrap;margin-top:12px';
      container.appendChild(actions);
      return actions;
    };

    if (result.view_url) {
      appendSummary('共分析 ' + (result.msg_count || 0).toLocaleString() + ' 条消息');
      const actions = createActions();
      const link = document.createElement('a');
      link.href = result.view_url;
      link.target = '_blank';
      link.textContent = '📊 在新标签页打开词云报告';
      link.className = 'btn btn-primary';
      link.style.textDecoration = 'none';
      actions.appendChild(link);
    } else if (result.download_url) {
      appendSummary('共导出 ' + (result.msg_count || 0).toLocaleString() + ' 条消息');
      const actions = createActions();
      const link = document.createElement('a');
      link.href = result.download_url;
      link.textContent = '📥 下载导出文件 (' + (result.filename || '') + ')';
      link.className = 'btn btn-primary';
      link.style.textDecoration = 'none';
      actions.appendChild(link);

      const againButton = document.createElement('button');
      againButton.type = 'button';
      againButton.className = 'btn btn-secondary';
      againButton.textContent = '再导一份';
      againButton.addEventListener('click', () => {
        if (!this.runBtn) return;
        this.runBtn.scrollIntoView({ behavior: 'smooth', block: 'center' });
        this.runBtn.focus({ preventScroll: true });
      });
      actions.appendChild(againButton);

      const isPathLike = typeof result.file === 'string' && (
        /[\\/]/.test(result.file) || /^[A-Za-z]:/.test(result.file)
      );
      if (isPathLike) {
        appendPath(result.file, false);
        const openBtn = document.createElement('button');
        openBtn.type = 'button';
        openBtn.className = 'btn btn-secondary';
        openBtn.textContent = '在文件夹中显示';
        openBtn.addEventListener('click', () => {
          openBtn.disabled = true;
          fetch('/api/util/open-path', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ path: result.file }),
          }).then((r) => r.json()).then((data) => {
            if (!data || !data.ok) {
              appendPath(result.file, true);
            }
          }).catch(() => {
            appendPath(result.file, true);
          }).finally(() => { openBtn.disabled = false; });
        });
        actions.appendChild(openBtn);
      }
    } else if (result.file) {
      appendPath(result.file, true);
      const actions = createActions();
      const openBtn = document.createElement('button');
      openBtn.type = 'button';
      openBtn.className = 'btn btn-secondary';
      openBtn.textContent = '在文件夹中显示';
      openBtn.addEventListener('click', () => {
        openBtn.disabled = true;
        fetch('/api/util/open-path', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ path: result.file }),
        }).then((r) => r.json()).then((data) => {
          if (!data || !data.ok) {
            /* path already shown with manual hint */
          }
        }).finally(() => { openBtn.disabled = false; });
      });
      actions.appendChild(openBtn);
    }

    if (result.note) {
      const note = document.createElement('p');
      note.style.cssText = 'color:var(--px-muted);font-size:12px;margin:10px 0 0 0;' +
        'max-width:640px;line-height:1.7';
      note.textContent = result.note;
      container.appendChild(note);
    }
  }
}
