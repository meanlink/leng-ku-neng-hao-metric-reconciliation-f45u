from fastapi import HTTPException

from .audit import record_action
from .bill_math import calculate_charges, explain_exceptions
from .bill_store import bill_history, insert_bill, save_decision
from .tariffs import editable_billing, latest_tariffs


def stale(bill, tariff, usage):
    return not bill['frozen_at'] and (bill['tariff_id'] != tariff['id'] or bill['reconciled_kwh'] != usage['actual_kwh'])


def submit_bill(cur, report, payload, user_id):
    usage = editable_billing(cur, report, payload.site)
    tariff = latest_tariffs(cur, report['id']).get(payload.site)
    if tariff is None:
        raise HTTPException(409, detail='请经理先登记该站点当月供电价表')
    history = bill_history(cur, report['id']).get(payload.site, [])
    if history:
        latest = history[0]
        if latest['status'] == 'pending':
            raise HTTPException(409, detail='请先处理当前待复核账单')
        if latest['status'] == 'approved' and not stale(latest, tariff, usage):
            raise HTTPException(409, detail='当前账单已复核通过')
    fields = payload.model_dump()
    fields.update(calculate_charges(usage['actual_kwh'], payload.observed_peak_kw, tariff))
    fields.update(tariff_id=tariff['id'], report_id=report['id'], revision=len(history) + 1, submitted_by=user_id)
    insert_bill(cur, fields)
    record_action(cur, user_id, 'submit_utility_bill', 'utility_bill', cur.lastrowid, payload.invoice_number)
    bill = bill_history(cur, report['id'])[payload.site][0]
    return {**bill, **explain_exceptions(bill)}


def review_bill(cur, report, bill_id, payload, user_id):
    histories = bill_history(cur, report['id'])
    bill = next((row for history in histories.values() for row in history if row['id'] == bill_id), None)
    if bill is None:
        raise HTTPException(404, detail='本月报中没有该供应商账单')
    usage = editable_billing(cur, report, bill['site'])
    tariff = latest_tariffs(cur, report['id'])[bill['site']]
    if bill['id'] != histories[bill['site']][0]['id'] or bill['status'] != 'pending':
        raise HTTPException(409, detail='只有最新待复核账单可以复核')
    if bill['submitted_by'] == user_id:
        raise HTTPException(409, detail='请由另一人复核该账单')
    if payload.decision == 'approved':
        if stale(bill, tariff, usage):
            raise HTTPException(409, detail='电量或价表已变更，请退回并按当前口径重新登记')
        if explain_exceptions(bill)['exceptions']:
            raise HTTPException(409, detail='账单仍有超差，请退回并核实账单或价表')
    save_decision(cur, bill_id, payload, user_id)
    record_action(cur, user_id, f'{payload.decision}_utility_bill', 'utility_bill', bill_id, payload.note)
    return bill_history(cur, report['id'])[bill['site']][0]
