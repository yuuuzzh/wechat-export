/* Multi-account workspace switcher in top nav */
(function () {
  function el(tag, attrs, html) {
    var n = document.createElement(tag);
    if (attrs) Object.keys(attrs).forEach(function (k) {
      if (k === 'className') n.className = attrs[k];
      else n.setAttribute(k, attrs[k]);
    });
    if (html != null) n.innerHTML = html;
    return n;
  }

  async function load() {
    var host = document.getElementById('workspace-switcher');
    if (!host) return;
    try {
      var r = await fetch('/api/workspace');
      var data = await r.json();
      if (!data.ok) return;
      host.innerHTML = '';
      var details = el('details', { className: 'theme-picker workspace-picker' });
      var cur = data.wxid || (data.current ? data.current.split(/[/\\]/).pop() : '工作区');
      var summary = el('summary', { title: data.current || '切换备份工作区' }, '工作区 · ' + String(cur).slice(0, 18));
      details.appendChild(summary);
      var menu = el('div', { className: 'theme-menu', role: 'listbox' });
      var accounts = data.accounts || [];
      if (!accounts.length) {
        menu.appendChild(el('div', { style: 'padding:8px 12px;font-size:12px;opacity:.7' }, '暂无备份，请先完成向导'));
        var setup = el('a', { href: '/setup', style: 'display:block;padding:8px 12px' }, '打开首次向导');
        menu.appendChild(setup);
      } else {
        accounts.forEach(function (acc) {
          var latest = acc.latest;
          if (!latest) return;
          var label = (acc.label || acc.wxid) + (acc.active ? ' ✓' : '');
          var btn = el('button', {
            type: 'button',
            role: 'option',
            'data-path': latest.path,
            'data-wxid': acc.wxid || '',
          }, label);
          if (acc.active) btn.setAttribute('aria-selected', 'true');
          btn.addEventListener('click', function () {
            switchTo(latest.path, acc.wxid || '');
          });
          menu.appendChild(btn);
          // Also list up to 2 older versions
          (acc.versions || []).slice(1, 3).forEach(function (v) {
            var sub = el('button', {
              type: 'button',
              role: 'option',
              style: 'opacity:.75;font-size:11px',
              'data-path': v.path,
              'data-wxid': acc.wxid || '',
            }, '↳ ' + (v.id || '').slice(0, 20) + (v.active ? ' ✓' : ''));
            sub.addEventListener('click', function () {
              switchTo(v.path, acc.wxid || '');
            });
            menu.appendChild(sub);
          });
        });
        menu.appendChild(el('a', { href: '/versions', style: 'display:block;padding:8px 12px;font-size:12px' }, '全部版本…'));
        menu.appendChild(el('a', { href: '/setup', style: 'display:block;padding:8px 12px;font-size:12px' }, '首次向导…'));
      }
      details.appendChild(menu);
      host.appendChild(details);
    } catch (e) { /* ignore */ }
  }

  async function switchTo(path, wxid) {
    try {
      var r = await fetch('/api/workspace/switch', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ path: path, wxid: wxid }),
      });
      var data = await r.json();
      if (!data.ok) {
        alert(data.error || '切换失败');
        return;
      }
      location.reload();
    } catch (e) {
      alert('切换失败: ' + e);
    }
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', load);
  } else {
    load();
  }
})();
