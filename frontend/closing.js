const reasons = { entry_error: '抄录错误', meter_factor: '电表倍率异常', throughput_recount: '吞吐吨日复盘' };
const decisions = { pending: ['warn', '待复核'], approved: ['green', '已批准'], rejected: ['red', '已驳回'] };

export function closingPages({ state, api, esc, fmt, render, toast }) {
  const canEdit = () => ['analyst', 'manager'].includes(state.user.role);
  const canReview = row => ['reviewer', 'manager'].includes(state.user.role) && row.submitted_by !== state.user.id;
  const amount = (value, decimals = 1) => value === null || value === undefined ? '—' : fmt(value, decimals);
  const badge = status => decisions[status] ? `<span class="tag ${decisions[status][0]}">${decisions[status][1]}</span>` : '';
  const button = (action, id, label, style = 'secondary') => `<button class="btn ${style}" data-close-action="${action}" data-id="${id}">${label}</button>`;
  const evidence = (key, label) => `<label class="field full">${label}<textarea name="${key}" required minlength="4" maxlength="500" rows="3"></textarea></label>`;
  const post = (path, payload, method = 'POST') => api(path, { method, body: JSON.stringify(payload) });
  let readings = [], corrections = [];

  function openForm(title, fields, submitLabel, submit, success) {
    const box = document.createElement('div');
    box.className = 'modal';
    box.innerHTML = `<section class="card" role="dialog" aria-label="${title}"><div class="section-title">${title}<button class="btn ghost" type="button" data-close-dialog>关闭</button></div>
      <form class="form-grid">${fields}<div class="field full"><button class="btn" type="submit">${submitLabel}</button></div></form></section>`;
    document.body.append(box);
    box.querySelector('[data-close-dialog]').onclick = () => box.remove();
    box.querySelector('form').onsubmit = async event => {
      event.preventDefault();
      const form = event.currentTarget;
      const submitButton = form.querySelector('[type=submit]');
      submitButton.disabled = true;
      try {
        await submit(Object.fromEntries(new FormData(form)));
        box.remove();
        toast(success);
        render();
      } catch (err) {
        toast(err.message);
        submitButton.disabled = false;
      }
    };
  }

  async function correctionsPage() {
    const [sources, queue, reports] = await Promise.all([api('/sources'), api('/reading-corrections'), api('/reports')]);
    const sourceId = state.correctionSource || sources[0]?.id;
    const entries = sourceId ? await api(`/sources/${sourceId}/readings`) : [];
    corrections = queue;
    readings = entries;
    const frozen = new Set(reports.filter(row => row.status === 'published').map(row => row.period));
    const pending = queue.filter(row => row.status === 'pending').length;
    const rows = readings.map(row => `<tr><td><b>${esc(row.reading_date)}</b><div class="kpi-label">${esc(row.import_batch)}</div></td>
      <td>${amount(row.value)} ${esc(row.unit)}<div class="kpi-label">${amount(row.throughput_ton_day)} 吨日</div></td>
      <td>${amount(row.effective_value)} ${esc(row.unit)}<div class="kpi-label">${amount(row.effective_ton_days)} 吨日</div></td>
      <td>${badge(row.correction_status) || (frozen.has(row.period) ? '<span class="kpi-label">月报已签发</span>' : canEdit() ? button('request', row.id, '提出更正') : '—')}</td></tr>`).join('');
    const reviewRows = queue.map(row => `<tr><td><b>#${row.id} · ${esc(row.source_code)}</b><div class="kpi-label">${esc(row.reading_date)} · ${esc(row.site)}</div></td>
      <td>${amount(row.original_value)} → <b>${amount(row.corrected_value)}</b> ${esc(row.unit)}<div class="kpi-label">${amount(row.original_ton_days)} → ${amount(row.corrected_ton_days)} 吨日</div></td>
      <td>${reasons[row.reason]}<div class="kpi-label closing-evidence">${esc(row.evidence)}</div></td>
      <td>${badge(row.status)}${row.decision_note ? `<div class="kpi-label closing-evidence">${esc(row.decision_note)}</div>` : ''}</td>
      <td>${row.status === 'pending' && canReview(row) ? `<div class="actions">${button('approve', row.id, '批准更正', '')}${button('reject', row.id, '驳回')}</div>` : '—'}</td></tr>`).join('');
    return `<section class="card"><div class="section-title">更正复核队列 <span class="tag warn">${pending} 待复核</span></div>
      <div class="notice">批准后保留原始读数，并按更正值重算差异单。已关闭的差异单会重新进入复核。</div>
      <div class="table-wrap"><table><thead><tr><th>电表与抄表日</th><th>原值 → 提议值</th><th>原因及证据</th><th>状态与意见</th><th>操作</th></tr></thead><tbody>${reviewRows || '<tr><td colspan="5" class="empty">暂无更正单</td></tr>'}</tbody></table></div></section>
      <section class="card closing-section"><div class="section-title">原始抄表与生效值<label class="closing-picker">电表来源<select id="correction-source">${sources.map(row => `<option value="${row.id}" ${row.id === sourceId ? 'selected' : ''}>${esc(row.source_code)} · ${esc(row.name)}</option>`).join('')}</select></label></div>
      <div class="table-wrap"><table><thead><tr><th>抄表日 / 批次</th><th>原始记录</th><th>当前核算值</th><th>动作</th></tr></thead><tbody>${rows || '<tr><td colspan="4" class="empty">该电表暂无抄表记录</td></tr>'}</tbody></table></div></section>`;
  }

  async function budgetsPage() {
    const reports = await api('/reports');
    const report = reports.find(row => row.id === state.budgetReport) || reports[0];
    if (!report) return `<div class="card empty">请先在月报发布生成草稿。 ${button('reports', 0, '打开月报发布')}</div>`;
    const sheet = await api(`/report-budgets/${report.id}`);
    const published = sheet.status === 'published';
    const summary = published ? sheet.enabled ? '签发时各站点电量、电价和成本均已冻结。' : '该月报未启用站点预算。'
      : sheet.enabled && sheet.missing_sites.length ? `签发前请配置以下站点的预算：${sheet.missing_sites.join('、')}`
      : '保存首个站点预算后，参与月报的所有站点均需配置。实施电价按元/千瓦时填写。';
    const rows = sheet.sites.map(row => `<tr><td><b>${esc(row.site)}</b><div class="kpi-label">${row.meter_count} 台纳入对账</div></td>
      <td>${amount(row.budget_kwh)}</td><td>${amount(row.actual_kwh)}</td><td>${amount(row.rate_cny_per_kwh, 4)}</td>
      <td>${amount(row.budget_cost, 2)}</td><td>${amount(row.actual_cost, 2)}</td>
      <td class="${row.variance_cost > 0 ? 'danger' : ''}">${amount(row.variance_cost, 2)}<div class="kpi-label">${amount(row.variance_kwh)} kWh</div></td>
      ${!published ? `<td>${!canEdit() ? '—' : button('budget', sheet.sites.indexOf(row), row.budget_kwh === null ? '设置预算' : '编辑预算')}</td>` : ''}</tr>`).join('');
    state.currentBudget = sheet;
    return `<section class="card"><div class="section-title">站点结算表 <label class="closing-picker">选择月报<select id="budget-report">${reports.map(row => `<option value="${row.id}" ${row.id === report.id ? 'selected' : ''}>${esc(row.period)} · ${esc(row.version)}</option>`).join('')}</select></label></div>
      <div class="closing-meta"><span class="tag ${published ? 'green' : 'warn'}">${published ? '已签发' : '草稿预览'}</span>${button('reports', 0, '查看月报台账')}</div><div class="notice ${sheet.missing_sites.length && sheet.enabled ? 'warn' : ''}">${esc(summary)}</div>
      <div class="table-wrap"><table><thead><tr><th>结算站点</th><th>预算 kWh</th><th>实际 kWh</th><th>电价 元/kWh</th><th>预算成本 元</th><th>实际成本 元</th><th>成本偏差 元</th>${!published ? '<th>操作</th>' : ''}</tr></thead><tbody>${rows || `<tr><td colspan="${published ? 7 : 8}" class="empty">暂无站点结算项目</td></tr>`}</tbody></table></div></section>`;
  }

  const actions = {
    'corrections': () => { state.page = 'corrections'; render(); },
    'reports': () => { state.page = 'reports'; render(); },
    'sheet': id => { state.budgetReport = id; state.page = 'budgets'; render(); },
    'request': id => {
      const row = readings.find(item => item.id === id);
      openForm('提出抄表更正', `<div class="notice full">${esc(row.reading_date)} · ${esc(row.import_batch)}</div>
        <label class="field full">原因<select name="reason">${Object.entries(reasons).map(([key, label]) => `<option value="${key}">${label}</option>`).join('')}</select></label>
        <label class="field">更正后电量（${esc(row.unit)}）<input type="number" name="corrected_value" min="0" step="0.001" value="${esc(row.value)}" required></label>
        <label class="field">更正后吞吐（吨日）<input type="number" name="corrected_ton_days" min="0" step="0.001" value="${esc(row.throughput_ton_day)}" required></label>${evidence('evidence', '工单或原表依据')}`,
        '提交更正', fields => post('/reading-corrections', { reading_id: id, ...fields }), '更正单已提交');
    },
    'approve': id => reviewCorrection(id, 'approved', '批准更正'),
    'reject': id => reviewCorrection(id, 'rejected', '驳回更正'),
    'budget': index => {
      const sheet = state.currentBudget;
      const site = sheet.sites[index];
      openForm('配置站点能耗预算', `<div class="notice full">${esc(sheet.period)} · ${esc(site.site)}</div>
        <label class="field">预算电量（kWh）<input name="budget_kwh" type="number" min="0.001" step="0.001" value="${esc(site.budget_kwh)}" required></label>
        <label class="field">电价（元/kWh）<input name="rate_cny_per_kwh" type="number" min="0.0001" max="9999.9999" step="0.0001" value="${esc(site.rate_cny_per_kwh)}" required></label>`,
        '保存预算', fields => post(`/report-budgets/${sheet.report_id}`, { site: site.site, ...fields }, 'PUT'), '站点预算已保存');
    },
  };

  function reviewCorrection(id, decision, label) {
    const row = corrections.find(item => item.id === id);
    openForm(label, `<div class="notice full">${esc(row.source_code)} · ${esc(row.reading_date)} · ${esc(row.evidence)}</div>${evidence('note', '复核意见')}`,
      label, fields => post(`/reading-corrections/${id}/decision`, { decision, ...fields }), '更正复核已保存');
  }

  function bind() {
    document.querySelectorAll('[data-close-action]').forEach(node => {
      node.onclick = () => actions[node.dataset.closeAction](Number(node.dataset.id));
    });
    document.querySelector('#correction-source')?.addEventListener('change', event => {
      state.correctionSource = Number(event.target.value);
      render();
    });
    document.querySelector('#budget-report')?.addEventListener('change', event => {
      state.budgetReport = Number(event.target.value);
      render();
    });
  }

  return { correctionsPage, budgetsPage, bind, button, openForm };
}
