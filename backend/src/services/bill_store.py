from fastapi import HTTPException


def bill_history(cur, report_id):
    cur.execute('''SELECT b.*, t.revision AS tariff_revision, t.contract_ref, t.charge_tolerance,
                          t.energy_rate, t.demand_rate, t.minimum_kw, t.fixed_fee,
                          u.name AS submitted_name, r.name AS reviewed_name
                   FROM utility_bill_revisions b JOIN site_tariffs t ON t.id=b.tariff_id
                   JOIN users u ON u.id=b.submitted_by LEFT JOIN users r ON r.id=b.reviewed_by
                   WHERE b.report_id=%s ORDER BY b.site,b.revision DESC''', (report_id,))
    histories = {}
    for row in cur.fetchall():
        histories.setdefault(row['site'], []).append(row)
    return histories


def insert_bill(cur, fields):
    cur.execute('''SELECT id FROM utility_bill_revisions
                   WHERE report_id=%(report_id)s AND invoice_number=%(invoice_number)s AND site<>%(site)s LIMIT 1''', fields)
    if cur.fetchone():
        raise HTTPException(409, detail='该供应商账单号已登记在本月另一站点')
    cur.execute('''INSERT INTO utility_bill_revisions(tariff_id,report_id,site,revision,invoice_number,evidence,
                        invoiced_kwh,observed_peak_kw,invoiced_demand_kw,invoice_subtotal,reconciled_kwh,
                        expected_demand_kw,energy_charge,demand_charge,expected_subtotal,submitted_by)
                   VALUES(%(tariff_id)s,%(report_id)s,%(site)s,%(revision)s,%(invoice_number)s,%(evidence)s,
                          %(invoiced_kwh)s,%(observed_peak_kw)s,%(invoiced_demand_kw)s,%(invoice_subtotal)s,
                          %(reconciled_kwh)s,%(expected_demand_kw)s,%(energy_charge)s,%(demand_charge)s,
                          %(expected_subtotal)s,%(submitted_by)s)''', fields)


def save_decision(cur, bill_id, payload, user_id):
    cur.execute('''UPDATE utility_bill_revisions SET status=%s,review_note=%s,reviewed_by=%s,reviewed_at=NOW()
                   WHERE id=%s AND status='pending' ''', (payload.decision, payload.note, user_id, bill_id))
    if cur.rowcount != 1:
        raise HTTPException(409, detail='该账单已复核')
