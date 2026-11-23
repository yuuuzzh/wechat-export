/* console_tip.js — Remind Windows users the black console window is expected */
(function () {
  const DISMISS_KEY = 'wechat-export-console-tip-dismissed';

  function isDismissed() {
    try { return localStorage.getItem(DISMISS_KEY) === '1'; } catch (e) { return false; }
  }

  function dismiss() {
    try { localStorage.setItem(DISMISS_KEY, '1'); } catch (e) { /* ignore */ }
  }

  function buildHtml() {
    return ''
      + '<div class="flow-callout-title">黑窗口是正常的</div>'
      + '<p style="margin:0;line-height:1.7">'
      + '启动后出现的黑色控制台是本机服务窗口，<strong>请勿关闭</strong>；关掉后网页就打不开了。'
      + '浏览器访问 <code>http://127.0.0.1:5000</code> 即可使用。'
      + '</p>'
      + '<div style="margin-top:12px">'
      + '<button type="button" class="btn btn-secondary console-tip-dismiss" style="font-size:11px">知道了，不再提示</button>'
      + '</div>';
  }

  function show(el) {
    if (!el) return;
    el.classList.add('flow-callout', 'flow-callout-warn');
    el.setAttribute('role', 'note');
    el.innerHTML = buildHtml();
    el.style.display = 'block';
    const btn = el.querySelector('.console-tip-dismiss');
    if (btn) {
      btn.addEventListener('click', function () {
        dismiss();
        document.querySelectorAll('[data-console-tip]').forEach(function (node) {
          node.style.display = 'none';
        });
      });
    }
  }

  function apply(platform) {
    if (isDismissed()) return;
    const system = (platform && platform.system) || '';
    // Show on Windows primarily; also show when platform unknown (exe users).
    if (system && system !== 'windows') return;
    document.querySelectorAll('[data-console-tip]').forEach(function (el) {
      show(el);
    });
  }

  function boot() {
    fetch('/api/health')
      .then(function (r) { return r.json(); })
      .then(function (data) { apply(data && data.platform); })
      .catch(function () { apply({ system: 'windows' }); });
  }

  window.ConsoleTip = { apply: apply, boot: boot, dismiss: dismiss };

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', boot);
  } else {
    boot();
  }
})();
