export function billingForms({ api, esc, openForm }) {
  const post = (path, payload) => api(path, { method: 'POST', body: JSON.stringify(payload) });
  const text = (name, label, value, max) => `<label class="field">${label}
    <input name="${name}" value="${esc(value)}" required minlength="4" maxlength="${max}"></label>`;
  const number = (name, label, value, step, min = 0) => `<label class="field">${label}
    <input type="number" name="${name}" value="${esc(value)}" step="${step}" min="${min}" required></label>`;
  const evidence = (name, label, value = '') => `<div class="field full">
    <label for="billing-field-${name}">${label}</label>
    <textarea id="billing-field-${name}" name="${name}" rows="3" required minlength="4" maxlength="500">${esc(value)}</textarea></div>`;
  const context = (sheet, row) => `<div class="notice full">${esc(sheet.period)} · ${esc(row.site)}</div>`;
  const root = sheet => `/utility-billing/${sheet.report_id}`;

  return {
    tariff(sheet, row) {
      const tariff = row.tariff || {};
      openForm('登记站点价表', `${context(sheet, row)}
        ${text('contract_ref', '合同或价表编号', tariff.contract_ref, 100)}
        ${number('energy_rate', '电量单价（元/kWh）', tariff.energy_rate, '0.0001', '0.0001')}
        ${number('demand_rate', '需量单价（元/kW）', tariff.demand_rate ?? 0, '0.0001')}
        ${number('minimum_kw', '合同最低需量（kW）', tariff.minimum_kw ?? 0, '0.001')}
        ${number('fixed_fee', '月固定费（元）', tariff.fixed_fee ?? 0, '0.01')}
        ${number('charge_tolerance', '金额容差（元）', tariff.charge_tolerance ?? 2, '0.01')}`,
        '保存价表', fields => post(`${root(sheet)}/tariffs`, {site: row.site, ...fields}), '价表已保存');
    },
    invoice(sheet, row) {
      const last = row.history[0] || {};
      openForm('提交供应商账单', `${context(sheet, row)}
        <div class="kpi-label full">使用账单上的未税小计，并从最大需量记录抄录实测值。按电量计费的站点可将需量两项填 0。</div>
        ${text('invoice_number', '供应商账单号', last.invoice_number, 80)}
        ${number('invoiced_kwh', '账单电量（kWh）', last.invoiced_kwh ?? row.actual_kwh, '0.001')}
        ${number('observed_peak_kw', '实测最大需量（kW）', last.observed_peak_kw ?? 0, '0.001')}
        ${number('invoiced_demand_kw', '账单计费需量（kW）', last.invoiced_demand_kw ?? 0, '0.001')}
        ${number('invoice_subtotal', '账单未税小计（元）', last.invoice_subtotal, '0.01')}
        ${evidence('evidence', '账单与最大需量记录依据', last.evidence)}`,
        '提交账单', fields => post(`${root(sheet)}/invoices`, {site: row.site, ...fields}), '账单已提交');
    },
    decision(sheet, row, decision) {
      const bill = row.history[0];
      const label = decision === 'approved' ? '批准账单' : '退回账单';
      openForm(label, `${context(sheet, row)}
        <div class="kpi-label full">${esc(bill.invoice_number)} · 第 ${bill.revision} 版 · ${esc(bill.evidence)}</div>
        ${evidence('note', '账单复核意见')}`, label,
        fields => post(`${root(sheet)}/invoices/${bill.id}/decision`, {decision, ...fields}), '复核意见已记录');
    },
  };
}
