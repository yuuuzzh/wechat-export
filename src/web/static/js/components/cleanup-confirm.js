// cleanup-confirm.js — three-stage confirmation modal for deletion
class CleanupConfirm extends Component {
  template(data) {
    if (!data.stage) return '';
    if (data.stage === 'preview') {
      var p = data.previewData;
      if (!p) return '';
      var fileListHtml = '';
      if (p.files_preview && p.files_preview.length) {
        fileListHtml = '<div class="cleanup-file-list">';
        p.files_preview.slice(0, 50).forEach(function(f) {
          fileListHtml += '<div class="cleanup-file-item"><code>' + escapeHtml(f.md5) + '</code> ' + formatSize(f.size) + '</div>';
        });
        if (p.files_preview.length > 50) {
          fileListHtml += '<div class="cleanup-file-more">...及其他 ' + (p.files_preview.length - 50).toLocaleString() + ' 个文件</div>';
        }
        fileListHtml += '</div>';
      }
      return '<div class="cleanup-modal-box">' +
        '<h3>&#x26a0; 删除媒体文件预览</h3>' +
        '<div class="cleanup-modal-stats">' +
        '<div class="cleanup-stat"><span class="cleanup-stat-num">' + p.total_messages.toLocaleString() + '</span> 条记录涉及媒体</div>' +
        '<div class="cleanup-stat"><span class="cleanup-stat-num">' + p.total_files.toLocaleString() + '</span> 个媒体文件将删除</div>' +
        '<div class="cleanup-stat"><span class="cleanup-stat-num">' + formatSize(p.total_bytes) + '</span> 预计释放空间</div>' +
        '</div>' +
        '<div role="alert" style="color:#f85149;font-size:13px;line-height:1.7;margin-top:16px">' +
        '<strong>将永久删除所选范围内的图片、视频和文件，删除后无法恢复。</strong><br>' +
        '<span style="color:#8b949e">文字聊天记录会保留，不会删除。</span>' +
        '</div>' +
        '<label class="check-row" style="margin:14px 0 0;display:flex;align-items:flex-start;gap:8px;font-size:13px;color:#e8f7ee">' +
        '<input type="checkbox" id="cleanup-ack" style="margin-top:3px">' +
        '<span>我了解：此操作不可恢复，且只会删媒体、保留文字记录</span></label>' +
        fileListHtml +
        '<div class="cleanup-modal-btns">' +
        '<button class="btn btn-secondary" id="cleanup-modal-cancel">取消</button>' +
        '<button class="btn btn-danger" id="cleanup-modal-confirm" disabled>确认，进入最终验证</button>' +
        '</div></div>';
    }
    if (data.stage === 'verify') {
      return '<div class="cleanup-modal-box">' +
        '<h3 style="color:#f85149">&#x1f6ab; 最终确认</h3>' +
        '<p style="font-size:14px;line-height:1.7;margin:16px 0">即将<strong>永久删除</strong>源微信存储中的图片/视频/文件；文字聊天记录仍会保留。此操作不可撤销。</p>' +
        '<p style="font-size:14px;margin:16px 0">请输入 <code>DELETE</code>，下方删除按钮才会启用：</p>' +
        '<input type="text" id="cleanup-delete-input" class="cleanup-delete-input" placeholder="输入 DELETE" autocomplete="off">' +
        '<div class="cleanup-modal-btns">' +
        '<button class="btn btn-secondary" id="cleanup-modal-cancel">取消</button>' +
        '<button class="btn btn-danger" id="cleanup-modal-verify" disabled>永久删除媒体文件</button>' +
        '</div></div>';
    }
    if (data.stage === 'executing') {
      return '<div class="cleanup-modal-box">' +
        '<h3>&#x23f3; 正在删除...</h3>' +
        '<div class="loading" style="margin:24px 0">执行中，请勿关闭页面...</div>' +
        '</div>';
    }
    if (data.stage === 'result') {
      var r = data.executeResult;
      if (!r) return '';
      var hasError = r.error || (r.errors && r.errors.length > 0);
      return '<div class="cleanup-modal-box">' +
        '<h3>' + (hasError ? '&#x26a0; 删除完成（部分错误）' : '&#x2705; 删除完成') + '</h3>' +
        '<div class="cleanup-modal-stats">' +
        '<div class="cleanup-stat"><span class="cleanup-stat-num">' + (r.deleted_files || 0).toLocaleString() + '</span> 个媒体文件已删除</div>' +
        '<div class="cleanup-stat"><span class="cleanup-stat-num">' + formatSize(r.freed_bytes || 0) + '</span> 空间已释放</div>' +
        '</div>' +
        (r.errors && r.errors.length > 0 ? '<div class="cleanup-modal-errors">' + r.errors.map(function(e) { return escapeHtml(e); }).join('<br>') + '</div>' : '') +
        '<div class="cleanup-modal-btns">' +
        '<button class="btn btn-primary" id="cleanup-modal-done">完成</button>' +
        '</div></div>';
    }
    return '';
  }

  mount() {
    var self = this;
    this.el.addEventListener('click', function(e) {
      var btn = e.target.closest('button');
      if (!btn) return;
      if (btn.id === 'cleanup-modal-cancel') {
        CleanupStore.emit('modal-cancel');
      } else if (btn.id === 'cleanup-modal-confirm') {
        var ack = document.getElementById('cleanup-ack');
        if (ack && !ack.checked) return;
        CleanupStore.emit('modal-verify');
      } else if (btn.id === 'cleanup-modal-verify') {
        CleanupStore.emit('modal-execute');
      } else if (btn.id === 'cleanup-modal-done') {
        CleanupStore.emit('modal-done');
      }
    });
    this.el.addEventListener('change', function(e) {
      if (e.target.id === 'cleanup-ack') {
        var btn = document.getElementById('cleanup-modal-confirm');
        if (btn) btn.disabled = !e.target.checked;
      }
    });
    CleanupStore.on('modal-stage-changed', function(stage) {
      self.render({ stage: stage, previewData: CleanupStore.data.previewData, executeResult: CleanupStore.data.executeResult });
      var backdrop = document.getElementById('cleanup-modal-backdrop');
      var modal = document.getElementById('cleanup-modal');
      if (stage) {
        if (backdrop) backdrop.style.display = 'block';
        if (modal) modal.style.display = 'flex';
      } else {
        if (backdrop) backdrop.style.display = 'none';
        if (modal) modal.style.display = 'none';
      }
      if (stage === 'verify') {
        setTimeout(function() {
          var el = document.getElementById('cleanup-delete-input');
          if (el) {
            el.value = '';
            el.focus();
            el.addEventListener('input', function() {
              var btn = document.getElementById('cleanup-modal-verify');
              if (btn) btn.disabled = (el.value !== 'DELETE');
            });
          }
        }, 100);
      }
    });
  }
}
