import { billingForms } from './billing-forms.js';

const readiness = {
  missing_tariff: ['warn', '缺少价表'], missing_invoice: ['warn', '待录账单'],
  pending: ['warn', '待复核'], exception: ['red', '账单超差'], stale: ['red', '口径已变更'],
  returned: ['red', '已退回'], approved: ['green', '已批准'], frozen: ['green', '已冻结'],
};
const exceptions = {meter_gap: '电量超差', demand_gap: '计费需量不符', charge_gap: '金额超差'};
const statusTag = key => `<span class="tag ${readiness[key][0]}">${readiness[key][1]}</span>`;
const money = value => Number(value || 0).toFixed(2);

export function billingPages({ state, api, esc, fmt, render, openForm }) {
  const forms = billingForms({ api, esc, openForm });
  let sheet;

  function action(name, index, label, style = 'secondary', creditId) {
    return `<button class="btn ${style}" data-billing="${name}" data-site-index="${index}"${creditId ? ` data-credit-id="${creditId}"` : ''}>${label}</button>`;
  }

  function rowActions(row, index) {
    if (sheet.status === 'published') return '';
    const {role, id} = state.user;
    const bill = row.history[0];
    const controls = [];
    if (role === 'manager') controls.push(action('tariff', index, row.tariff ? '修订价表' : '登记价表'));
    if (row.tariff && ['analyst', 'manager'].includes(role) && bill?.status !== 'pending' && row.readiness !== 'approved') {
      controls.push(action('invoice', index, bill ? '重新登记账单' : '登记账单', ''));
    }
    if (bill?.status === 'pending' && bill.submitted_by !== id && ['reviewer', 'manager'].includes(role)) {
      if (row.readiness === 'pending') controls.push(action('approved', index, '批准账单', ''));
      controls.push(action('returned', index, '退回账单'));
    }
    return controls.join('');
  }

  function history(rows) {
    if (!rows.length) return '';
    return `<details class="billing-history"><summary>账单记录（${rows.length} 版）</summary>
      <ol>${rows.map(row => `<li><b>第 ${row.revision} 版 · ${esc(row.invoice_number)}</b> ${statusTag(row.status)}
        <div>价表 ${esc(row.contract_ref)} v${row.tariff_revision} · 登记 ${esc(row.submitted_name)} · 实测最大需量 ${fmt(row.observed_peak_kw, 3)} kW</div>
        <div>电量费 ${fmt(row.energy_charge, 2)} + 需量费 ${fmt(row.demand_charge, 2)} + 固定费 ${fmt(row.fixed_fee, 2)} = ${fmt(row.expected_subtotal, 2)} 元</div>
        <div>${esc(row.evidence)}</div>${row.review_note ? `<div>复核 ${esc(row.reviewed_name)} · ${esc(row.review_note)}</div>` : ''}</li>`).join('')}</ol></details>`;
  }

  function creditSection(row, index) {
    const {credits, origin_bills} = row.credit;
    const canFile = ['analyst', 'manager'].includes(state.user.role);
    const canAllocate = sheet.status === 'draft' && Boolean(row.tariff) && ['analyst', 'manager'].includes(state.user.role);
    const rows = credits.map(credit => {
      const applied = credit.applications.length
        ? `<table class="billing-compare"><thead><tr><th>抵扣月份</th><th>抵扣账单</th><th>抵扣额 元</th><th>抵扣前余额</th><th>抵扣后余额</th><th>原冻结账单</th></tr></thead><tbody>${credit.applications.map(app =>
            `<tr><td>${esc(app.applied_period)}</td><td>${esc(app.bill_invoice_number)} 第 ${app.bill_revision} 版</td><td>${money(app.amount)}</td><td>${money(app.balance_before)}</td><td>${money(app.balance_after)}</td><td>${esc(app.origin_period)} · ${esc(app.origin_invoice_number)}</td></tr>`).join('')}</tbody></table>`
        : '';
      const allocate = canAllocate
        ? `<div class="actions">${action('allocate', index, credit.allocated_amount === null ? '分摊到本月' : '修改分摊', 'secondary', credit.id)}</div>`
        : '';
      return `<div class="billing-credit">
        <b>${esc(credit.credit_number)}</b> · 原账单 ${esc(credit.origin_period)} ${esc(credit.origin_invoice_number)}<div class="kpi-label">贷项金额 ${money(credit.amount)} 元 · 可用余额 ${money(credit.remaining_amount)} 元 · 本月分摊 ${credit.allocated_amount === null ? '—' : money(credit.allocated_amount) + ' 元'}</div>
        <div class="kpi-label">${esc(credit.evidence)}</div>${applied}${allocate}</div>`;
    }).join('');
    const filing = canFile && origin_bills.length ? `<div class="actions">${action('credit', index, '登记贷项单')}</div>` : '';
    if (!rows && !filing) return '';
    return `<div class="billing-credits"><div class="section-title" style="font-size:14px">贷项单</div>${rows || '<div class="kpi-label">暂无贷项单</div>'}${filing}</div>`;
  }

  function siteCard(row, index) {
    const { tariff } = row;
    const bill = row.history[0];
    const reading = row.readiness === 'frozen' ? bill.reconciled_kwh : row.actual_kwh;
    const applied = row.credit.applications
      .filter(app => Number(app.report_id) === Number(sheet.report_id))
      .reduce((total, app) => total + Number(app.amount), 0);
    const netPayable = bill && applied
      ? `<div class="billing-net">贷项抵扣 ${money(applied)} 元 · 抵扣后应付 ${money(Number(bill.invoice_subtotal) - applied)} 元</div>` : '';
    const summary = bill ? `<table class="billing-compare"><thead><tr><th>核验项目</th><th>核算值</th><th>账单值</th><th>差额</th></tr></thead><tbody>
      <tr><th scope="row">电量 kWh</th><td>${fmt(bill.reconciled_kwh, 3)}</td><td>${fmt(bill.invoiced_kwh, 3)}</td><td>${fmt(bill.meter_gap, 3)}</td></tr>
      <tr><th scope="row">计费需量 kW</th><td>${fmt(bill.expected_demand_kw, 3)}</td><td>${fmt(bill.invoiced_demand_kw, 3)}</td><td>${fmt(bill.demand_gap, 3)}</td></tr>
      <tr><th scope="row">未税小计 元</th><td>${fmt(bill.expected_subtotal, 2)}</td><td>${fmt(bill.invoice_subtotal, 2)}</td><td>${fmt(bill.charge_gap, 2)}</td></tr></tbody></table>
      ${bill.exceptions.length ? `<div class="notice warn">${bill.exceptions.map(code => exceptions[code]).join(' · ')}</div>` : ''}` : '';
    return `<section class="card billing-site" aria-label="${esc(row.site)}">
      <div class="section-title">${esc(row.site)} ${statusTag(row.readiness)}</div>
      <p class="kpi-label">对账电量 ${fmt(reading, 3)} kWh · ${row.meter_count} 个电表</p>
      ${tariff ? `<div class="billing-tariff"><b>${esc(tariff.contract_ref)} v${tariff.revision}</b>
        <div>${fmt(tariff.energy_rate, 4)} 元/kWh · ${fmt(tariff.demand_rate, 4)} 元/kW · 最低 ${fmt(tariff.minimum_kw, 3)} kW</div>
        <div>月固定费 ${fmt(tariff.fixed_fee, 2)} 元 · 金额容差 ${fmt(tariff.charge_tolerance, 2)} 元</div></div>` : ''}
      ${bill ? `<p><b>${esc(bill.invoice_number)}</b> · 第 ${bill.revision} 版 · 价表 v${bill.tariff_revision}</p>` : ''}
      ${summary}${netPayable}${bill?.frozen_at ? `<div class="kpi-label">冻结于 ${esc(bill.frozen_at.replace('T', ' '))}</div>` : ''}${creditSection(row, index)}<div class="actions billing-actions">${rowActions(row, index)}</div>${history(row.history)}</section>`;
  }

  async function page() {
    const reports = await api('/reports');
    if (!reports.length) return '<section class="card"><div class="section-title">供应商账单</div><p>请先在月报发布页生成草稿。</p></section>';
    const selected = reports.find(report => report.id === state.billingReport) || reports[0];
    sheet = await api(`/utility-billing/${selected.id}`);
    const blockerCount = sheet.sites.filter(row => !['approved', 'frozen'].includes(row.readiness)).length;
    const message = sheet.status === 'published' && sheet.enabled ? '月报已签发，以下账单为签发时的冻结快照。'
      : sheet.status === 'published' ? '此月报在签发时未启用供应商账单核验。'
      : sheet.enabled ? `签发前须完成所有站点的账单复核。待完成 ${blockerCount} 个站点。贷项单签发时按分摊额抵扣同站账单。`
      : '经理登记第一张站点价表后，本月报启用供应商账单核验。';
    return `<section class="card billing-summary"><div class="section-title">站点账单核验
      <label class="closing-picker">核算周期<select id="billing-report">${reports.map(report =>
        `<option value="${report.id}" ${report.id === selected.id ? 'selected' : ''}>${esc(report.period)}</option>`).join('')}</select></label>
      </div><div class="notice">${message}</div></section>
      <div class="grid two billing-sites">${sheet.sites.map(siteCard).join('') ||
        '<div class="card empty">请先生成本月报的站点差异复核单。</div>'}</div>`;
  }

  function bind() {
    document.querySelector('#billing-report')?.addEventListener('change', event => {
      state.billingReport = Number(event.target.value);
      render();
    });
    document.querySelectorAll('[data-billing-jump]').forEach(button => button.onclick = () => {
      state.billingReport = Number(button.dataset.billingJump);
      state.page = 'billing';
      render();
    });
    document.querySelectorAll('[data-billing]').forEach(button => button.onclick = () => {
      const row = sheet.sites[Number(button.dataset.siteIndex)];
      const command = button.dataset.billing;
      if (command === 'tariff' || command === 'invoice' || command === 'credit') forms[command](sheet, row);
      else if (command === 'allocate') {
        const credit = row.credit.credits.find(item => String(item.id) === button.dataset.creditId);
        forms.allocate(sheet, row, credit);
      } else forms.decision(sheet, row, command);
    });
  }

  return { page, bind };
}
