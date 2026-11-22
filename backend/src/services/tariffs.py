from fastapi import HTTPException

from .audit import record_action
from .budgets import site_actuals


def editable_billing(cur, report, site):
    if report['status'] != 'draft':
        raise HTTPException(409, detail='月报已签发，账单核验已冻结')
    cur.execute('SELECT unit, cycle FROM metric_contracts WHERE id=%s', (report['contract_id'],))
    contract = cur.fetchone()
    if (contract['unit'], contract['cycle']) != ('kWh', 'monthly'):
        raise HTTPException(422, detail='仅月度 kWh 指标可核验供应商账单')
    usage = site_actuals(cur, report).get(site)
    if usage is None:
        raise HTTPException(422, detail='请选择本月报差异复核单中的站点')
    return usage


def latest_tariffs(cur, report_id):
    cur.execute('''SELECT * FROM site_tariffs WHERE report_id=%s ORDER BY site, revision''', (report_id,))
    return {tariff['site']: tariff for tariff in cur.fetchall()}


def add_tariff(cur, report, payload, user_id):
    editable_billing(cur, report, payload.site)
    current = latest_tariffs(cur, report['id']).get(payload.site)
    fields = payload.model_dump()
    if current and all(current[key] == value for key, value in fields.items()):
        return current
    fields.update(report_id=report['id'], revision=current['revision'] + 1 if current else 1, created_by=user_id)
    cur.execute('''INSERT INTO site_tariffs(report_id,site,revision,contract_ref,energy_rate,demand_rate,
                        minimum_kw,fixed_fee,charge_tolerance,created_by)
                   VALUES(%(report_id)s,%(site)s,%(revision)s,%(contract_ref)s,%(energy_rate)s,%(demand_rate)s,
                          %(minimum_kw)s,%(fixed_fee)s,%(charge_tolerance)s,%(created_by)s)''', fields)
    new_id = cur.lastrowid
    record_action(cur, user_id, 'save_utility_tariff', 'site_tariff', new_id, payload.contract_ref)
    cur.execute('SELECT * FROM site_tariffs WHERE id=%s', (new_id,))
    return cur.fetchone()
