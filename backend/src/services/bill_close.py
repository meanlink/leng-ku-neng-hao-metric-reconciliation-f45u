from fastapi import HTTPException

from .bill_math import explain_exceptions
from .bill_review import stale
from .bill_store import bill_history
from .budgets import site_actuals
from .tariffs import latest_tariffs


def billing_sheet(cur, report):
    tariffs = latest_tariffs(cur, report['id'])
    histories = bill_history(cur, report['id'])
    sites = []
    for site, usage in site_actuals(cur, report).items():
        tariff = tariffs.get(site)
        history = [{**row, **explain_exceptions(row)} for row in histories.get(site, [])]
        latest = history[0] if history else None
        if not tariff:
            readiness = 'missing_tariff'
        elif not latest:
            readiness = 'missing_invoice'
        elif latest['frozen_at']:
            readiness = 'frozen'
        elif latest['status'] == 'returned':
            readiness = 'returned'
        elif stale(latest, tariff, usage):
            readiness = 'stale'
        elif latest['exceptions']:
            readiness = 'exception'
        else:
            readiness = latest['status']
        sites.append({**usage, 'tariff': tariff, 'history': history, 'readiness': readiness})
    return {'report_id': report['id'], 'period': report['period'], 'status': report['status'],
            'enabled': bool(tariffs), 'sites': sites}


def freeze_bills(cur, report):
    sheet = billing_sheet(cur, report)
    if not sheet['enabled']:
        return
    blockers = [row['site'] for row in sheet['sites'] if row['readiness'] != 'approved']
    if blockers:
        raise HTTPException(409, detail='以下站点账单尚未通过最新口径核验：' + '、'.join(blockers))
    cur.executemany('UPDATE utility_bill_revisions SET frozen_at=NOW() WHERE id=%s',
                    [(row['history'][0]['id'],) for row in sheet['sites']])
