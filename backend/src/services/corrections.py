from fastapi import HTTPException

from ..db import db_cursor
from .audit import record_action
from .budgets import refresh_draft
from .energy import calculate_case, update_reopened_case


def reading_snapshot(cur, reading_id):
    cur.execute("SELECT * FROM meter_readings WHERE id=%s", (reading_id,))
    reading = cur.fetchone()
    if not reading:
        raise HTTPException(404, detail="抄表记录不存在")
    return reading


def correction_period(correction_id):
    with db_cursor() as cur:
        cur.execute("""SELECT r.period FROM reading_corrections c JOIN meter_readings r ON r.id=c.reading_id
                       WHERE c.id=%s""", (correction_id,))
        row = cur.fetchone()
        if not row:
            raise HTTPException(404, detail="抄表更正单不存在")
        return row['period']


def ensure_period_open(cur, period):
    cur.execute("SELECT id FROM monthly_reports WHERE period=%s AND status='published'", (period,))
    if cur.fetchone():
        raise HTTPException(409, detail="本月报已签发，抄表更正已冻结")


def create_correction(cur, payload, reading, user_id):
    ensure_period_open(cur, reading['period'])
    cur.execute("SELECT id FROM reading_corrections WHERE active_reading_id=%s", (reading['id'],))
    if cur.fetchone():
        raise HTTPException(409, detail="该抄表记录已有待复核或已批准的更正")
    value_changed = payload.corrected_value != reading['value']
    tons_changed = payload.corrected_ton_days != reading['throughput_ton_day']
    if not value_changed and not tons_changed:
        raise HTTPException(422, detail="更正值必须与原始记录有差异")
    if payload.reason == 'meter_factor' and tons_changed:
        raise HTTPException(422, detail="倍率异常仅能更正电量")
    if payload.reason == 'throughput_recount' and value_changed:
        raise HTTPException(422, detail="吞吐复盘仅能更正吨日")
    cur.execute("""INSERT INTO reading_corrections(reading_id,corrected_value,corrected_ton_days,reason,evidence,submitted_by)
                   VALUES(%s,%s,%s,%s,%s,%s)""", (reading['id'], payload.corrected_value, payload.corrected_ton_days,
                                                  payload.reason, payload.evidence, user_id))
    row_id = cur.lastrowid
    record_action(cur, user_id, 'submit_reading_correction', 'reading_correction', row_id, payload.evidence)
    cur.execute("SELECT * FROM reading_corrections WHERE id=%s", (row_id,))
    return cur.fetchone()


def recalculate_source_cases(cur, reading, reason):
    cur.execute("SELECT id,contract_id FROM reconciliation_cases WHERE period=%s AND source_id=%s",
                (reading['period'], reading['source_id']))
    for case in cur.fetchall():
        result = calculate_case(cur, reading['period'], reading['source_id'], case['contract_id'])
        update_reopened_case(cur, case['id'], result, reason)
        refresh_draft(cur, reading['period'], case['contract_id'])


def decide_correction(cur, row_id, payload, user_id):
    cur.execute("SELECT * FROM reading_corrections WHERE id=%s", (row_id,))
    row = cur.fetchone()
    reading = reading_snapshot(cur, row['reading_id'])
    ensure_period_open(cur, reading['period'])
    if row['status'] != 'pending':
        raise HTTPException(409, detail="只有待复核的更正单才能处理")
    if int(user_id) == row['submitted_by']:
        raise HTTPException(409, detail="更正单须由另一位人员复核")
    cur.execute("""UPDATE reading_corrections SET status=%s, decided_by=%s, decided_at=NOW(), decision_note=%s WHERE id=%s""",
                (payload.decision, user_id, payload.note, row_id))
    if payload.decision == 'approved':
        recalculate_source_cases(cur, reading, f"抄表更正 #{row_id} 已生效，重新复核")
    record_action(cur, user_id, f'{payload.decision}_reading_correction', 'reading_correction', row_id, payload.note)
    cur.execute("SELECT * FROM reading_corrections WHERE id=%s", (row_id,))
    return cur.fetchone()


def has_pending_corrections(cur, period, contract_id):
    cur.execute("""SELECT c.id FROM reading_corrections c JOIN meter_readings r ON c.active_reading_id=r.id
                   JOIN reconciliation_cases a ON a.period=r.period AND a.source_id=r.source_id
                   WHERE a.period=%s AND a.contract_id=%s AND c.status='pending' LIMIT 1""", (period, contract_id))
    return cur.fetchone() is not None
