from decimal import Decimal, ROUND_HALF_UP

from fastapi import HTTPException

from ..db import db_cursor
from .energy import quant


def report_by_id(cur, report_id):
    cur.execute("SELECT * FROM monthly_reports WHERE id=%s", (report_id,))
    report = cur.fetchone()
    if not report:
        raise HTTPException(404, detail="月报不存在")
    return report


def report_period(report_id):
    with db_cursor() as cur:
        return report_by_id(cur, report_id)["period"]


def aggregate_totals(cur, period, contract_id):
    cur.execute("""SELECT COALESCE(SUM(actual_kwh),0) AS actual_kwh, COALESCE(SUM(expected_kwh),0) AS expected_kwh,
                   COUNT(*) AS case_count FROM reconciliation_cases WHERE period=%s AND contract_id=%s""",
                (period, contract_id))
    totals = cur.fetchone()
    actual, expected = totals["actual_kwh"], totals["expected_kwh"]
    rate = quant((actual - expected) / expected * 100) if expected else Decimal(0)
    return actual, expected, rate, totals["case_count"]


def refresh_draft(cur, period, contract_id):
    totals = aggregate_totals(cur, period, contract_id)
    cur.execute("""UPDATE monthly_reports SET actual_kwh=%s, expected_kwh=%s, difference_rate=%s, case_count=%s
                   WHERE period=%s AND contract_id=%s AND status='draft'""", (*totals, period, contract_id))


def site_actuals(cur, report):
    cur.execute("""SELECT s.site, COUNT(*) AS meter_count, SUM(r.actual_kwh) AS actual_kwh
                   FROM reconciliation_cases r JOIN meter_sources s ON s.id=r.source_id
                   WHERE r.period=%s AND r.contract_id=%s GROUP BY s.site ORDER BY s.site""",
                (report["period"], report["contract_id"]))
    return {row["site"]: row for row in cur.fetchall()}


def stored_budgets(cur, report_id):
    cur.execute("SELECT * FROM monthly_site_budgets WHERE report_id=%s ORDER BY site", (report_id,))
    return {row["site"]: row for row in cur.fetchall()}


def rounded_cost(kwh, rate):
    return (kwh * rate).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def summarize_site(actual, budget, published):
    row = {**actual, 'budget_kwh': None, 'rate_cny_per_kwh': None, 'budget_cost': None,
           'actual_cost': None, 'variance_kwh': None, 'variance_cost': None, 'updated_by': None, 'updated_at': None}
    if budget:
        budget_kwh, rate = budget['budget_kwh'], budget['rate_cny_per_kwh']
        budget_cost = budget['frozen_budget_cost'] if published else rounded_cost(budget_kwh, rate)
        actual_cost = budget['frozen_actual_cost'] if published else rounded_cost(actual['actual_kwh'], rate)
        row.update(budget_kwh=budget_kwh, rate_cny_per_kwh=rate, budget_cost=budget_cost, actual_cost=actual_cost,
                   variance_kwh=actual['actual_kwh'] - budget_kwh, variance_cost=actual_cost - budget_cost,
                   updated_by=budget['updated_by'], updated_at=budget['updated_at'])
    return row


def budget_sheet(cur, report):
    budgets = stored_budgets(cur, report['id'])
    published = report['status'] == 'published'
    actuals = ({site: {'site': site, 'actual_kwh': row['frozen_actual_kwh'], 'meter_count': row['frozen_meter_count']}
                for site, row in budgets.items()} if published else site_actuals(cur, report))
    rows = [summarize_site(actual, budgets.get(site), published) for site, actual in actuals.items()]
    return {'report_id': report['id'], 'period': report['period'], 'status': report['status'],
            'enabled': bool(budgets), 'missing_sites': [site for site in actuals if site not in budgets], 'sites': rows}


def save_site_budget(cur, report, payload, user_id):
    if report['status'] != 'draft':
        raise HTTPException(409, detail="月报已签发，站点预算已冻结")
    cur.execute("SELECT unit,cycle FROM metric_contracts WHERE id=%s", (report['contract_id'],))
    contract = cur.fetchone()
    if contract['unit'] != 'kWh' or contract['cycle'] != 'monthly':
        raise HTTPException(422, detail="只有 kWh 月度指标可以配置电价结算")
    if payload.site not in site_actuals(cur, report):
        raise HTTPException(422, detail="请选择本月报差异复核单中的站点")
    cur.execute("""INSERT INTO monthly_site_budgets(report_id,site,budget_kwh,rate_cny_per_kwh,updated_by,updated_at)
                   VALUES(%s,%s,%s,%s,%s,NOW()) ON DUPLICATE KEY UPDATE budget_kwh=VALUES(budget_kwh),
                   rate_cny_per_kwh=VALUES(rate_cny_per_kwh),updated_by=VALUES(updated_by),updated_at=VALUES(updated_at)""",
                (report['id'], payload.site, payload.budget_kwh, payload.rate_cny_per_kwh, user_id))


def freeze_budgets(cur, report):
    sheet = budget_sheet(cur, report)
    if not sheet['enabled']:
        return
    if sheet['missing_sites']:
        raise HTTPException(409, detail="请先配置全部站点的能耗预算：" + "、".join(sheet['missing_sites']))
    for row in sheet['sites']:
        cur.execute("""UPDATE monthly_site_budgets SET frozen_actual_kwh=%s, frozen_meter_count=%s,
                       frozen_budget_cost=%s, frozen_actual_cost=%s WHERE report_id=%s AND site=%s""",
                    (row['actual_kwh'], row['meter_count'], row['budget_cost'], row['actual_cost'], report['id'], row['site']))
