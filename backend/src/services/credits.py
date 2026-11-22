from decimal import Decimal

import pymysql
from fastapi import HTTPException

from .audit import record_action
from .bill_store import bill_history
from .budgets import site_actuals
from .credit_math import plan_credit_applications

NOTE_COLUMNS = '''n.*, u.name AS registered_name, ob.invoice_number AS origin_invoice_number,
                   ob.revision AS origin_bill_revision, ob.invoice_subtotal AS origin_invoice_subtotal,
                   ob.expected_subtotal AS origin_expected_subtotal, rp.period AS origin_period'''


def credit_notes_for_sites(cur, sites):
    if not sites:
        return {}
    placeholders = ','.join(['%s'] * len(sites))
    cur.execute(f'''SELECT {NOTE_COLUMNS}
                    FROM supplier_credit_notes n
                    JOIN utility_bill_revisions ob ON ob.id=n.origin_bill_id
                    JOIN monthly_reports rp ON rp.id=n.origin_report_id
                    JOIN users u ON u.id=n.registered_by
                    WHERE n.site IN ({placeholders}) ORDER BY n.site, n.id''', list(sites))
    notes = {}
    for row in cur.fetchall():
        notes.setdefault(row['site'], []).append(row)
    return notes


def origin_bills_for_sites(cur, sites):
    if not sites:
        return {}
    placeholders = ','.join(['%s'] * len(sites))
    cur.execute(f'''SELECT b.id, b.site, b.invoice_number, b.revision, b.invoice_subtotal,
                           b.expected_subtotal, b.frozen_at, rp.id AS origin_report_id, rp.period AS origin_period
                    FROM utility_bill_revisions b JOIN monthly_reports rp ON rp.id=b.report_id
                    WHERE b.site IN ({placeholders}) AND b.frozen_at IS NOT NULL
                    ORDER BY rp.period DESC, b.revision DESC''', list(sites))
    bills = {}
    for row in cur.fetchall():
        bills.setdefault(row['site'], []).append(row)
    return bills


def allocations_for_report(cur, report_id):
    cur.execute('SELECT * FROM credit_allocations WHERE report_id=%s', (report_id,))
    return {row['credit_id']: row for row in cur.fetchall()}


def applications_for_notes(cur, note_ids):
    """All deduction records for the given credit notes, across every report."""
    if not note_ids:
        return []
    placeholders = ','.join(['%s'] * len(note_ids))
    cur.execute(f'''SELECT a.*, n.credit_number, n.site AS credit_site, n.origin_bill_id,
                          ob.invoice_number AS origin_invoice_number, rp.period AS origin_period,
                          b.invoice_number AS bill_invoice_number, b.revision AS bill_revision,
                          br.period AS applied_period, u.name AS applied_name
                   FROM credit_applications a
                   JOIN supplier_credit_notes n ON n.id=a.credit_id
                   JOIN utility_bill_revisions ob ON ob.id=n.origin_bill_id
                   JOIN monthly_reports rp ON rp.id=n.origin_report_id
                   JOIN utility_bill_revisions b ON b.id=a.bill_id
                   JOIN monthly_reports br ON br.id=a.report_id
                   JOIN users u ON u.id=a.applied_by
                   WHERE a.credit_id IN ({placeholders}) ORDER BY a.site, a.credit_id, a.id''',
                sorted(note_ids))
    return cur.fetchall()


def site_credit_view(cur, report, sites):
    notes = credit_notes_for_sites(cur, sites)
    origins = origin_bills_for_sites(cur, sites)
    allocations = allocations_for_report(cur, report['id'])
    applications = applications_for_notes(cur, {note['id'] for rows in notes.values() for note in rows})
    applied = {}
    for row in applications:
        applied.setdefault((row['site'], row['credit_id']), []).append(row)
    view = {}
    for site in sites:
        credits = []
        for note in notes.get(site, []):
            allocation = allocations.get(note['id'])
            rows = applied.get((site, note['id']), [])
            credits.append({**note,
                            'allocated_amount': allocation['amount'] if allocation else None,
                            'applications': rows,
                            'applied_amount': sum((row['amount'] for row in rows), Decimal('0'))})
        view[site] = {'credits': credits, 'origin_bills': origins.get(site, []),
                      'applications': [row for row in applications
                                       if row['site'] == site and row['report_id'] == report['id']]}
    return view


def register_credit(cur, report, payload, user_id):
    cur.execute('''SELECT b.*, rp.status AS report_status
                   FROM utility_bill_revisions b JOIN monthly_reports rp ON rp.id=b.report_id
                   WHERE b.id=%s''', (payload.origin_bill_id,))
    origin = cur.fetchone()
    if origin is None:
        raise HTTPException(404, detail='原冻结账单不存在')
    if origin['report_status'] != 'published' or origin['frozen_at'] is None:
        raise HTTPException(409, detail='只能按已签发月报中的原冻结账单登记贷项单')
    if origin['site'] != payload.site:
        raise HTTPException(422, detail='贷项单站点须与原冻结账单站点一致')
    cur.execute('SELECT id FROM supplier_credit_notes WHERE site=%s AND credit_number=%s',
                (payload.site, payload.credit_number))
    if cur.fetchone():
        raise HTTPException(409, detail='该站点此贷项单号已登记，不能重复入账')
    try:
        cur.execute('''INSERT INTO supplier_credit_notes(site,credit_number,origin_report_id,origin_bill_id,
                            amount,remaining_amount,evidence,registered_by)
                       VALUES(%s,%s,%s,%s,%s,%s,%s,%s)''',
                    (payload.site, payload.credit_number, origin['report_id'], origin['id'],
                     payload.amount, payload.amount, payload.evidence, user_id))
    except pymysql.err.IntegrityError as exc:
        raise HTTPException(409, detail='该站点此贷项单号已登记，不能重复入账') from exc
    credit_id = cur.lastrowid
    record_action(cur, user_id, 'register_supplier_credit', 'supplier_credit_note', credit_id,
                  f"{payload.site} {payload.credit_number}")
    cur.execute(f'''SELECT {NOTE_COLUMNS} FROM supplier_credit_notes n
                    JOIN utility_bill_revisions ob ON ob.id=n.origin_bill_id
                    JOIN monthly_reports rp ON rp.id=n.origin_report_id
                    JOIN users u ON u.id=n.registered_by WHERE n.id=%s''', (credit_id,))
    note = cur.fetchone()
    return {**note, 'allocated_amount': None, 'applications': [], 'applied_amount': Decimal('0')}


def set_allocation(cur, report, credit_id, amount, user_id):
    if report['status'] != 'draft':
        raise HTTPException(409, detail='月报已签发，贷项分摊已冻结')
    cur.execute('SELECT * FROM supplier_credit_notes WHERE id=%s', (credit_id,))
    note = cur.fetchone()
    if note is None:
        raise HTTPException(404, detail='贷项单不存在')
    if note['site'] not in site_actuals(cur, report):
        raise HTTPException(422, detail='贷项单站点不在本月报核验站点中')
    cur.execute('SELECT id FROM site_tariffs WHERE report_id=%s AND site=%s ORDER BY revision DESC LIMIT 1',
                (report['id'], note['site']))
    if not cur.fetchone():
        raise HTTPException(409, detail='请经理先登记该站点当月供电价表，再分摊贷项金额')
    amount = Decimal(amount)
    if amount <= 0:
        cur.execute('DELETE FROM credit_allocations WHERE credit_id=%s AND report_id=%s',
                    (credit_id, report['id']))
        record_action(cur, user_id, 'clear_supplier_credit_allocation', 'supplier_credit_note',
                      credit_id, report['period'])
        return None
    if amount > note['remaining_amount']:
        raise HTTPException(409, detail='分摊金额不能超过贷项单当前可用余额')
    cur.execute('''INSERT INTO credit_allocations(credit_id,report_id,site,amount,created_by)
                   VALUES(%s,%s,%s,%s,%s)
                   ON DUPLICATE KEY UPDATE amount=VALUES(amount),created_by=VALUES(created_by),updated_at=NOW()''',
                (credit_id, report['id'], note['site'], amount, user_id))
    record_action(cur, user_id, 'allocate_supplier_credit', 'supplier_credit_note', credit_id,
                  f"{report['period']} {amount}")
    cur.execute('SELECT * FROM credit_allocations WHERE credit_id=%s AND report_id=%s',
                (credit_id, report['id']))
    return cur.fetchone()


def apply_credits(cur, report, user_id):
    """Deduct this report's credit allocations from the site credit balances.

    Runs inside the publish transaction, so a rejection keeps both the balances
    and the report untouched (the report stays a draft).  Publication switches
    the report to published in the same transaction, and a retry short-circuits
    on the published status, so a failed issuance can never deduct twice.
    """
    cur.execute('SELECT credit_id, site, amount FROM credit_allocations WHERE report_id=%s ORDER BY site, credit_id',
                (report['id'],))
    allocations = cur.fetchall()
    if not allocations:
        return []
    per_site = {}
    for row in allocations:
        per_site.setdefault(row['site'], []).append(row)
    histories = bill_history(cur, report['id'])
    for site, rows in per_site.items():
        history = histories.get(site)
        if not history:
            raise HTTPException(409, detail=f'{site} 尚未登记供应商账单，不能抵扣贷项')
        bill = history[0]
        if bill['status'] != 'approved' or bill['frozen_at'] is None:
            raise HTTPException(409, detail=f'{site} 最新账单未通过复核，不能抵扣贷项')
        if sum((row['amount'] for row in rows), Decimal('0')) > bill['invoice_subtotal']:
            raise HTTPException(409, detail=f'{site} 贷项分摊额超过账单未税小计')
    note_ids = sorted({row['credit_id'] for row in allocations})
    placeholders = ','.join(['%s'] * len(note_ids))
    cur.execute(f'SELECT id, remaining_amount FROM supplier_credit_notes WHERE id IN ({placeholders}) '
                'ORDER BY id FOR UPDATE', note_ids)
    balances = {row['id']: row['remaining_amount'] for row in cur.fetchall()}
    applications = []
    for site, rows in per_site.items():
        bill = histories[site][0]
        allocated = sum((row['amount'] for row in rows), Decimal('0'))
        ordered = [(row['credit_id'], balances[row['credit_id']]) for row in rows]
        planned, shortfall = plan_credit_applications(ordered, allocated)
        if shortfall > 0:
            raise HTTPException(409, detail=f'{site} 可用贷项余额不足，月报保持草稿')
        for credit_id, amount, before, after in planned:
            cur.execute('''INSERT INTO credit_applications(credit_id,report_id,site,bill_id,amount,
                                balance_before,balance_after,applied_by)
                           VALUES(%s,%s,%s,%s,%s,%s,%s,%s)''',
                        (credit_id, report['id'], site, bill['id'], amount, before, after, user_id))
            cur.execute('UPDATE supplier_credit_notes SET remaining_amount=%s WHERE id=%s', (after, credit_id))
            balances[credit_id] = after
            applications.append({'credit_id': credit_id, 'site': site, 'bill_id': bill['id'],
                                 'amount': amount, 'balance_before': before, 'balance_after': after})
        record_action(cur, user_id, 'apply_supplier_credit', 'monthly_report', report['id'],
                      f'{site} 抵扣 {allocated} 元')
    return applications
