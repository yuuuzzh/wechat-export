/* mac_guide.js — Show low-risk Mac workflow tips; advanced helper mode is opt-in */
(function () {
  const DISMISS_KEY = 'wechat-export-mac-guide-dismissed';

  function isDismissed() {
    try { return localStorage.getItem(DISMISS_KEY) === '1'; } catch (e) { return false; }
  }

  function dismiss() {
    try { localStorage.setItem(DISMISS_KEY, '1'); } catch (e) { /* ignore */ }
  }

  function buildGuideHtml(opts) {
    opts = opts || {};
    const compact = !!opts.compact;
    let html = '<div class="flow-callout-title">macOS 低风险用法（推荐）</div>';
    html += '<p style="margin:0 0 8px 0;line-height:1.7">';
    html += '默认路线<strong>不会</strong>自动挂接微信进程取密钥；这样比「每次扫描进程」更不容易触发微信环境异常。';
    html += '高级模式（自备 helper，需临时关 SIP + 管理员授权）见 docs/mac-auto-key.md，';
    html += '我们<strong>不能保证永不风控</strong>。';
    html += '</p>';
    if (!compact) {
      html += '<ol style="margin:0;padding-left:18px;line-height:1.75">';
      html += '<li><b>密钥只准备一次</b>：用已有密钥粘贴到「手动输入密钥」，或直接打开已解密备份目录。</li>';
      html += '<li><b>日常只碰本地文件</b>：备份 / 导出 / 搜索时尽量不依赖「挂进程取钥」；分析阶段可先退出微信。</li>';
      html += '<li><b>读沙盒目录</b>：系统设置 → 隐私与安全性 → 完全磁盘访问权限，允许 Terminal / Python / 本程序。</li>';
      html += '<li><b>高级模式才需要</b>：临时关闭 SIP、管理员授权、微信停在登录页；'
        + '完成后重新开启 SIP。默认路线不要 chmod 整个微信目录、不要装注入类插件、不要反复附着进程。</li>';
      html += '</ol>';
      html += '<p style="margin:10px 0 0;line-height:1.7;font-size:12px;color:var(--px-muted)">';
      html += '不知道密钥从哪来 / 想用高级提钥？先看 <a href="/mac-keys-guide" style="color:inherit"><b>Mac 使用新手指引（四条路线）</b></a>。';
      html += '路径示例：<code>~/Library/Containers/com.tencent.xinWeChat/Data/Documents/xwechat_files/&lt;账号&gt;/db_storage</code>';
      html += '</p>';
    } else {
      html += '<p style="margin:0;line-height:1.7">Mac <b>默认不能</b>一键提钥（高级模式需自备 helper 与临时关 SIP）。请先看';
      html += '<a href="/mac-keys-guide">新手指引</a>，再「手动输入密钥」或打开已解密备份。';
      html += '需要完全磁盘访问才能读微信沙盒目录。</p>';
    }
    html += '<div style="margin-top:12px;display:flex;gap:8px;flex-wrap:wrap">';
    const path = (window.location && window.location.pathname) || '';
    if (path.indexOf('/mac-keys-guide') !== 0) {
      html += '<a class="btn btn-primary" style="text-decoration:none;font-size:11px" href="/mac-keys-guide">Mac 使用新手指引</a>';
    }
    if (path.indexOf('/keys') !== 0) {
      html += '<a class="btn btn-secondary" style="text-decoration:none;font-size:11px" href="/keys">手动输入密钥</a>';
    }
    if (path.indexOf('/backup') !== 0) {
      html += '<a class="btn btn-secondary" style="text-decoration:none;font-size:11px" href="/backup">一键备份</a>';
    }
    html += '<button type="button" class="btn btn-secondary mac-guide-dismiss" style="font-size:11px">知道了，收起</button>';
    html += '</div>';
    return html;
  }

  function showOn(el, platform, opts) {
    if (!el) return;
    el.classList.add('flow-callout', 'flow-callout-mac');
    el.setAttribute('role', 'note');
    el.innerHTML = buildGuideHtml(opts);
    el.style.display = 'block';
    const btn = el.querySelector('.mac-guide-dismiss');
    if (btn) {
      btn.addEventListener('click', function () {
        dismiss();
        document.querySelectorAll('[data-mac-guide]').forEach(function (node) {
          node.style.display = 'none';
        });
      });
    }
  }

  function apply(platform) {
    if (!platform) return;
    const needGuide = platform.system === 'macos' || platform.auto_key_extract === false;
    if (!needGuide) return;
    if (isDismissed()) return;
    const nodes = document.querySelectorAll('[data-mac-guide]');
    nodes.forEach(function (el) {
      const compact = el.getAttribute('data-mac-guide') === 'compact';
      showOn(el, platform, { compact: compact });
    });
  }

  function boot() {
    fetch('/api/health')
      .then(function (r) { return r.json(); })
      .then(function (data) {
        apply(data && data.platform);
      })
      .catch(function () { /* ignore */ });
  }

  window.MacGuide = { apply: apply, boot: boot, dismiss: dismiss };

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', boot);
  } else {
    boot();
  }
})();
