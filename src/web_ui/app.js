(function () {
  'use strict';

  var TOKEN = document.body.getAttribute('data-token') || '';
  var state = null;
  var busy = false;

  var ALIGNMENT_STAGES = {
    company_pool: '企业池筛选',
    evidence: '证据采集',
    requirement: '需求分析',
    execution_plan: '执行方案',
    executing: '执行期',
  };
  var NEXT_TOOL_LABELS = {
    select_target_companies: '筛选并确认目标企业池',
    collect_company_evidence: '采集岗位与面经证据',
    analyze_company_requirements: '分析企业需求',
    save_requirement_profile: '保存需求分析',
    plan_execution_alignment: '准备执行方案校准',
    save_execution_alignment: '保存并应用执行方案',
  };

  function withToken(url) {
    if (!url) return '';
    return url + (url.indexOf('?') >= 0 ? '&' : '?') + 'token=' + encodeURIComponent(TOKEN);
  }

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

  function postJSON(path, body) {
    return api(path, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body || {}),
    });
  }

  function findTask(id) {
    var found = null;
    (state.phases || []).forEach(function (phase) {
      (phase.tasks || []).forEach(function (task) {
        if (task.id === id) found = task;
      });
    });
    return found;
  }

  function loadState() {
    return api('/api/state').then(function (data) {
      state = data;
      render();
    }).catch(function (err) {
      document.getElementById('sub').textContent = '无法读取档案：' + err.message;
      document.getElementById('warnings').innerHTML =
        '<div class="warn-box">本地服务不可用或 token 已失效。请从桌面快捷方式重新打开控制台。</div>';
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
          + '</label>'
          + '<button class="ck-btn ghost" data-action="edit" data-id="' + esc(t.id) + '">编辑</button>'
          + taskDetail(t) + '</div>');
      });
    } else if (ph.milestone_tasks && ph.milestone_tasks.length) {
      lines.push('<div class="empty">里程碑已规划；回到对话里细化当前阶段后会变成可打卡任务。</div>');
      lines.push('<ul class="ms-preview">' + ph.milestone_tasks.map(function (m) {
        var pr = { high: 'pr-high', medium: 'pr-medium', low: 'pr-low' }[m.priority] || 'pr-medium';
        var done = m.done_criteria ? '：' + esc(m.done_criteria) : '';
        return '<li><span class="pr ' + pr + '"></span>' + esc(m.name) + done + '</li>';
      }).join('') + '</ul>');
    } else {
      lines.push('<div class="empty">还没有细化任务。回到对话里让 AI 细化当前阶段。</div>');
    }
    return '<div class="card"><div class="card-head"><span class="card-title">'
      + esc(ph.name) + '<span class="type-pill">' + esc(ph.type) + '</span>' + badge + '</span>'
      + '<span class="muted">' + ph.done + '/' + ph.total + ' · ' + pct + '%</span></div>'
      + '<div class="bar"><div class="fill" style="width:' + pct + '%"></div></div>'
      + (ph.company ? '<div class="company">' + esc(ph.company) + '</div>' : '')
      + (ph.goal ? '<div class="goal">' + esc(ph.goal) + '</div>' : '')
      + '<div class="tasks">' + lines.join('') + '</div></div>';
  }

  function renderAlignment() {
    var el = document.getElementById('alignment');
    if (!el) return;
    var a = state.alignment;
    if (!a) { el.innerHTML = ''; return; }
    var started = a.stage || a.company_pool || a.evidence || a.requirement || a.execution_plan;
    var stageLabel = a.stage ? (ALIGNMENT_STAGES[a.stage] || a.stage) : '';
    var head = '<div class="card-head"><span class="card-title">企业适配'
      + (stageLabel ? '<span class="type-pill">' + esc(stageLabel) + '</span>' : '')
      + '</span>'
      + (a.next_tool && NEXT_TOOL_LABELS[a.next_tool]
        ? '<span class="muted">下一步：' + esc(NEXT_TOOL_LABELS[a.next_tool]) + '</span>' : '')
      + '</div>';
    if (!started) {
      el.innerHTML = '<div class="card">' + head + '<div class="empty">尚未开始企业适配</div></div>';
      return;
    }
    var rows = [];
    var pool = a.company_pool;
    if (pool) {
      var pc = pool.counts || {};
      var total = pc.total != null
        ? pc.total : (pool.scrapable || []).length + (pool.not_scrapable || []).length;
      rows.push('<div class="align-row"><span class="align-label">企业池</span><span>'
        + total + ' 家 · 可抓 ' + (pool.scrapable || []).length
        + ' / 未接入 ' + (pool.not_scrapable || []).length + '</span></div>');
    }
    var ev = a.evidence;
    if (ev) {
      var ec = ev.counts || {};
      var cf = ev.confidence || {};
      var links = [];
      if (ev.report_html) links.push('<a href="' + esc(withToken(ev.report_html)) + '" target="_blank" rel="noopener">阅读版</a>');
      if (ev.report_md) links.push('<a href="' + esc(withToken(ev.report_md)) + '" target="_blank" rel="noopener">全文</a>');
      if (ev.index) links.push('<a href="' + esc(withToken(ev.index)) + '" target="_blank" rel="noopener">原始数据</a>');
      rows.push('<div class="align-row"><span class="align-label">证据</span><span>'
        + 'JD ' + (ec.kept_jobs != null ? ec.kept_jobs : 0)
        + ' 条 · 面经 ' + (ec.interviews || 0) + ' 条 · 置信度 '
        + esc(cf.jd || '未知') + ' / ' + esc(cf.interview || '未知')
        + (links.length ? ' · ' + links.join(' · ') : '')
        + '</span></div>');
    }
    var req = a.requirement;
    if (req) {
      rows.push('<div class="align-row"><span class="align-label">需求</span><span>'
        + '高频项 ' + req.high_frequency_count + ' 条 · 硬门槛 ' + req.hard_requirement_count
        + ' 条 · 置信度 ' + esc(req.confidence_jd || '未知') + ' / '
        + esc(req.confidence_interview || '未知') + '</span></div>');
    }
    var plan = a.execution_plan;
    if (plan) {
      rows.push('<div class="align-row"><span class="align-label">执行版</span><span>'
        + (plan.applied ? '已应用' : '待应用') + ' · ' + plan.phase_count + ' 个阶段'
        + (plan.strategy_summary ? ' · ' + esc(plan.strategy_summary) : '')
        + (plan.diff_summary ? ' · ' + esc(plan.diff_summary) : '')
        + '</span></div>');
    }
    if (!rows.length) rows.push('<div class="empty">暂无适配产物</div>');
    el.innerHTML = '<div class="card">' + head + '<div class="align-grid">'
      + rows.join('') + '</div></div>';
  }

  function renderResearch() {
    var el = document.getElementById('research');
    var r = state.research;
    if (!r || !r.counts) { el.innerHTML = ''; return; }
    var counts = r.counts || {};
    var links = '';
    if (r.report_html) links += '<a href="' + esc(withToken(r.report_html)) + '" target="_blank" rel="noopener">阅读版</a>';
    if (r.report_md) links += ' · <a href="' + esc(withToken(r.report_md)) + '" target="_blank" rel="noopener">可读全文</a>';
    if (r.report_json) links += ' · <a href="' + esc(withToken(r.report_json)) + '" target="_blank" rel="noopener">原始数据</a>';
    var failed = (r.failed_sources || []).length
      ? '<div class="muted">失败源：' + esc(r.failed_sources.join('、')) + '</div>' : '';
    el.innerHTML = '<div class="card"><div class="card-head"><span class="card-title">市场调研'
      + '<span class="type-pill">来源真实</span></span>'
      + '<span class="muted">' + esc(r.generated_at || '') + '</span></div>'
      + '<div class="goal">岗位 ' + (counts.jd_samples || 0) + ' 条 · 案例 '
      + (counts.cases || 0) + ' 条</div>' + failed
      + (links ? '<div class="task-res">' + links + '</div>' : '')
      + '</div>';
  }

  function renderReports() {
    var el = document.getElementById('reports');
    var reports = state.reports || [];
    if (!reports.length) { el.innerHTML = ''; return; }
    el.innerHTML = '<div class="card"><div class="card-head"><span class="card-title">调研报告'
      + '<span class="type-pill">' + reports.length + ' 份</span></span></div>'
      + '<input id="report-search" placeholder="按方向筛选，如 AI Agent" '
      + 'style="margin-top:10px;padding:7px 10px;border:1px solid var(--line);border-radius:8px;width:100%">'
      + '<ul class="ms-preview" id="report-list"></ul></div>';
    var input = document.getElementById('report-search');
    var paint = function () {
      var q = (input.value || '').trim().toLowerCase();
      var list = document.getElementById('report-list');
      var filtered = reports.filter(function (r) {
        return !q || String(r.direction || '').toLowerCase().indexOf(q) >= 0;
      });
      if (!filtered.length) {
        list.innerHTML = '<li class="muted">没有匹配的报告</li>';
        return;
      }
      list.innerHTML = filtered.map(function (r) {
        var counts = r.counts || {};
        var links = [];
        if (r.html) links.push('<a href="' + esc(withToken(r.html)) + '" target="_blank" rel="noopener">阅读版</a>');
        if (r.md) links.push('<a href="' + esc(withToken(r.md)) + '" target="_blank" rel="noopener">全文</a>');
        if (r.json) links.push('<a href="' + esc(withToken(r.json)) + '" target="_blank" rel="noopener">原始数据</a>');
        var failed = (r.failed_sources || []).length
          ? ' · 失败源：' + esc(r.failed_sources.join('、')) : '';
        return '<li><strong>' + esc(r.direction) + '</strong>'
          + ' <span class="muted">' + esc(r.generated_at || '') + '</span>'
          + '<br><span class="muted">岗位 ' + (counts.jd_samples || 0)
          + ' · 案例 ' + (counts.cases || 0) + failed + '</span>'
          + (links.length ? '<br>' + links.join(' · ') : '') + '</li>';
      }).join('');
    };
    input.addEventListener('input', paint);
    paint();
  }

  function editTask(id) {
    var task = findTask(id);
    if (!task) return;
    var name = prompt('任务名', task.name);
    if (name === null) return;
    var desc = prompt('描述', task.desc || '');
    if (desc === null) return;
    var how = prompt('怎么做（分号分隔）', (task.how_to || []).join('；'));
    if (how === null) return;
    var done = prompt('完成标准', task.done_criteria || '');
    if (done === null) return;
    var priority = prompt('优先级 high/medium/low', task.priority || 'medium');
    if (priority === null) return;
    var mode = prompt('打卡方式 once/daily/percent', task.checkin_mode || 'once');
    if (mode === null) return;
    var goal = prompt('目标（daily 天数 / percent 百分比）', String(task.checkin_goal || 0));
    if (goal === null) return;
    postJSON('/api/task', {
      task_id: id,
      name: name,
      description: desc,
      how_to: how.split(/[；;\n]/).map(function (s) { return s.trim(); }).filter(Boolean),
      done_criteria: done,
      priority: priority,
      checkin_mode: mode,
      checkin_goal: parseFloat(goal) || 0,
    }).then(function (data) {
      state = data.state;
      render();
      toast('任务已保存');
    }).catch(function (err) { toast(err.message); });
  }

  function renderApplications() {
    var el = document.getElementById('applications');
    var apps = state.applications || [];
    if (!apps.length) { el.innerHTML = ''; return; }
    var labels = {
      applied: '已投递', screening: '进初筛', interview: '进面试',
      offer: 'offer', rejected: '已拒绝', withdrawn: '已撤回',
    };
    el.innerHTML = '<div class="card"><div class="card-head"><span class="card-title">求职漏斗</span>'
      + '<span class="muted">最近 ' + apps.length + ' 条</span></div>'
      + '<ul class="ms-preview">' + apps.map(function (a) {
        return '<li>' + esc(a.company) + (a.role ? ' · ' + esc(a.role) : '')
          + ' <span class="muted">' + esc(labels[a.status] || a.status) + '</span></li>';
      }).join('') + '</ul></div>';
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
    document.getElementById('total-done').textContent = (state.all_complete ? '全部完成 · ' : '')
      + state.total_done + ' / ' + state.total_tasks + ' 个任务';
    var link = document.getElementById('assets-link');
    if (state.assets_index) link.href = withToken(state.assets_index);
    var mapLink = document.getElementById('map-link');
    if (mapLink) mapLink.href = '/roadmap?token=' + encodeURIComponent(TOKEN);

    var warn = document.getElementById('warnings');
    if (state.warnings && state.warnings.length) {
      warn.innerHTML = '<div class="warn-box">' + state.warnings.map(esc).join('<br>') + '</div>';
    } else {
      warn.innerHTML = '';
    }

    document.getElementById('phases').innerHTML = state.phases.map(renderPhase).join('');
    renderAlignment();
    renderResearch();
    renderReports();
    renderApplications();
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
    else if (action === 'edit') editTask(id);
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

  document.getElementById('app-form').addEventListener('submit', function (e) {
    e.preventDefault();
    var form = e.target;
    var payload = {
      company: form.company.value,
      role: form.role.value,
      channel: form.channel.value,
      status: form.status.value,
    };
    postJSON('/api/application', payload).then(function (data) {
      state = data.state;
      form.reset();
      render();
      toast('投递已登记');
    }).catch(function (err) { toast(err.message); });
  });

  if (window.EventSource) {
    var events = new EventSource('/api/events?token=' + encodeURIComponent(TOKEN));
    events.onmessage = function () { loadState(); };
  }

  loadState();
})();
