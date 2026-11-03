(function () {
  'use strict';

  var TOKEN = document.body.getAttribute('data-token') || '';
  var state = null;
  var busy = false;

  function esc(s) {
    return String(s == null ? '' : s)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
  }

  function toast(msg) {
    var t = document.getElementById('toast');
    t.textContent = msg;
    t.classList.add('show');
    setTimeout(function () { t.classList.remove('show'); }, 1800);
  }

  function api(path, opts) {
    opts = opts || {};
    opts.headers = Object.assign({ 'X-CK-Token': TOKEN }, opts.headers || {});
    return fetch(path, opts).then(function (res) {
      return res.json().then(function (data) {
        if (!res.ok) throw new Error(data.message || data.error || '请求失败');
        return data;
      });
    });
  }

  function loadState() {
    return api('/api/state').then(function (data) {
      state = data;
      render();
    }).catch(function (err) {
      toast(err.message);
    });
  }

  function taskControl(t) {
    var tid = esc(t.id);
    if (t.status === 'completed' || t.status === 'skipped') {
      return '<span class="done-badge">完成</span>'
        + ' <button class="ck-btn ghost" data-action="undo" data-id="' + tid + '">撤销</button>';
    }
    if (t.checkin_mode === 'daily') {
      return '<span class="ck-ctl">打卡 ' + Math.floor(t.checkin_progress) + '/'
        + (t.checkin_goal || '?') + ' 天'
        + ' <button class="ck-btn" data-action="daily" data-id="' + tid + '">今天打卡</button>'
        + '</span>';
    }
    if (t.checkin_mode === 'percent') {
      return '<span class="ck-ctl">进度 ' + Math.floor(t.checkin_progress) + '%/'
        + (t.checkin_goal || 100) + '%'
        + ' <input type="range" min="0" max="' + (t.checkin_goal || 100)
        + '" value="' + Math.floor(t.checkin_progress)
        + '" data-action="percent" data-id="' + tid + '"></span>';
    }
    return '<input type="checkbox" data-action="once" data-id="' + tid + '">';
  }

  function taskDetail(t) {
    var parts = '';
    if (t.done_criteria) parts += '<div class="task-done">完成标准：' + esc(t.done_criteria) + '</div>';
    if (t.how_to && t.how_to.length) {
      parts += '<ol>' + t.how_to.map(function (h) { return '<li>' + esc(h) + '</li>'; }).join('') + '</ol>';
    }
    if (t.resources && t.resources.length) {
      var links = t.resources.map(function (r) {
        var label = esc(r.label || '资源');
        if (r.url) return '<a href="' + esc(r.url) + '" target="_blank" rel="noopener">' + label + '</a>';
        if (r.search) return '<span>' + label + '（搜索：' + esc(r.search) + '）</span>';
        return '';
      }).filter(Boolean).join(' · ');
      if (links) parts += '<div class="task-res">资源：' + links + '</div>';
    }
    if (!parts) return '';
    return '<details class="task-detail"><summary>怎么做 / 完成标准</summary>' + parts + '</details>';
  }

  function renderPhase(ph) {
    var pct = ph.total ? Math.round(ph.done / ph.total * 100) : 0;
    var badge = ph.is_current ? '<span class="badge current">当前阶段</span>' : '';
    var lines = [];
    if (ph.tasks.length) {
      var lastMs = null;
      var stats = {};
      ph.tasks.forEach(function (t) {
        if (!t.milestone_id) return;
        var s = stats[t.milestone_id] || { done: 0, total: 0 };
        s.total += 1;
        if (t.status === 'completed' || t.status === 'skipped') s.done += 1;
        stats[t.milestone_id] = s;
      });
      ph.tasks.forEach(function (t) {
        if (t.milestone_id && t.milestone_id !== lastMs) {
          lastMs = t.milestone_id;
          var s = stats[t.milestone_id] || { done: 0, total: 0 };
          var name = ph.milestone_names[t.milestone_id] || t.milestone_id;
          lines.push('<div class="ms">里程碑：' + esc(name) + '（' + s.done + '/' + s.total + '）</div>');
        }
        var pr = { high: 'pr-high', medium: 'pr-medium', low: 'pr-low' }[t.priority] || 'pr-medium';
        var nameCls = (t.status === 'completed' || t.status === 'skipped') ? 'task-name done' : 'task-name';
        lines.push('<div class="task-wrap"><label class="task">'
          + taskControl(t)
          + '<span class="' + nameCls + '"><span class="pr ' + pr + '"></span>' + esc(t.name) + '</span>'
          + '<span class="task-meta">' + esc(t.id) + '</span>'
          + '</label>' + taskDetail(t) + '</div>');
      });
    } else {
      lines.push('<div class="empty">还没有细化任务。回到对话里让 AI 细化当前阶段，或先按里程碑查看规划。</div>');
    }
    return '<div class="card"><div class="card-head"><span class="card-title">'
      + esc(ph.name) + '<span class="type-pill">' + esc(ph.type) + '</span>' + badge + '</span>'
      + '<span class="muted">' + ph.done + '/' + ph.total + ' · ' + pct + '%</span></div>'
      + '<div class="bar"><div class="fill" style="width:' + pct + '%"></div></div>'
      + (ph.company ? '<div class="company">' + esc(ph.company) + '</div>' : '')
      + (ph.goal ? '<div class="goal">' + esc(ph.goal) + '</div>' : '')
      + '<div class="tasks">' + lines.join('') + '</div></div>';
  }

  function render() {
    if (!state) return;
    var sub = document.getElementById('sub');
    sub.textContent = '档案：' + state.profile + ' · 目标档位参考：' + (state.start_level || '未判定');
    document.getElementById('start-level').textContent = state.strategy || '';
    var totalPct = state.total_tasks ? Math.round(state.total_done / state.total_tasks * 100) : 0;
    document.getElementById('ring').style.setProperty('--p', totalPct);
    document.getElementById('ring-pct').textContent = totalPct + '%';
    document.getElementById('total-pct').textContent = totalPct + '%';
    document.getElementById('total-done').textContent = state.total_done + ' / ' + state.total_tasks + ' 个任务';
    var link = document.getElementById('assets-link');
    if (state.assets_index) link.href = state.assets_index;

    var warn = document.getElementById('warnings');
    if (state.warnings && state.warnings.length) {
      warn.innerHTML = '<div class="warn-box">' + state.warnings.map(esc).join('<br>') + '</div>';
    } else {
      warn.innerHTML = '';
    }

    document.getElementById('phases').innerHTML = state.phases.map(renderPhase).join('');
  }

  function setBusy(value) {
    busy = value;
    document.querySelectorAll('button, input[type=range]').forEach(function (el) {
      el.disabled = value;
    });
  }

  function checkin(taskId, status, amount) {
    if (busy) return;
    setBusy(true);
    api('/api/checkin', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ task_id: taskId, status: status, amount: amount || 0 }),
    }).then(function (data) {
      state = data.state;
      render();
      toast('已同步到档案');
    }).catch(function (err) {
      toast(err.message);
    }).finally(function () {
      setBusy(false);
    });
  }

  document.getElementById('phases').addEventListener('click', function (e) {
    var btn = e.target.closest('[data-action]');
    if (!btn) return;
    var action = btn.getAttribute('data-action');
    var id = btn.getAttribute('data-id');
    if (action === 'daily') checkin(id, 'completed', 1);
    else if (action === 'undo') checkin(id, 'pending', 0);
  });

  document.getElementById('phases').addEventListener('change', function (e) {
    var el = e.target;
    var action = el.getAttribute && el.getAttribute('data-action');
    var id = el.getAttribute && el.getAttribute('data-id');
    if (action === 'once' && el.checked) checkin(id, 'completed', 1);
    else if (action === 'percent') {
      checkin(id, 'completed', parseFloat(el.value));
    }
  });

  document.getElementById('refresh').addEventListener('click', function () {
    loadState().then(function () { toast('已刷新'); });
  });

  loadState();
})();
