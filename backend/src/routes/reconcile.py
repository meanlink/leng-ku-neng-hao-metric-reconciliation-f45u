from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from ..closing_schemas import Period
from ..db import db_cursor, lock_period
from ..security import current_user, require_roles
from ..services.audit import record_action
from ..services.budgets import refresh_draft
from ..services.energy import calculate_case, update_reopened_case

router = APIRouter(prefix="/reconcile", tags=["reconcile"])


class RunIn(BaseModel):
    period: Period
    source_id: int = Field(gt=0)
    contract_id: int = Field(gt=0)


class ReviewIn(BaseModel):
    action: Literal['confirm', 'reject', 'close']
    note: str = Field(default='', max_length=500)


def ensure_case_period_editable(cur, period, contract_id):
    cur.execute("SELECT id FROM monthly_reports WHERE period=%s AND contract_id=%s AND status='published'", (period, contract_id))
    if cur.fetchone():
        raise HTTPException(409, detail="月报已签发，差异复核单已冻结")


@router.post("/run")
def run(payload: RunIn, user=Depends(require_roles("analyst", "manager"))):
    params = (payload.period, payload.source_id, payload.contract_id)
    case_sql = "SELECT * FROM reconciliation_cases WHERE period=%s AND source_id=%s AND contract_id=%s"
    with db_cursor(commit=True) as cur:
        lock_period(cur, payload.period)
        result = calculate_case(cur, *params)
        ensure_case_period_editable(cur, payload.period, payload.contract_id)
        cur.execute(case_sql, params)
        case = cur.fetchone()
        if not case:
            cur.execute("""INSERT INTO reconciliation_cases(period,source_id,contract_id,actual_kwh,expected_kwh,
                           difference_kwh,difference_rate,unit,cycle,issue_note)
                           VALUES(%(period)s,%(source_id)s,%(contract_id)s,%(actual_kwh)s,%(expected_kwh)s,
                           %(difference_kwh)s,%(difference_rate)s,%(unit)s,%(cycle)s,%(issue_note)s)""", result)
        elif any(case[field] != result[field] for field in ('actual_kwh', 'expected_kwh', 'unit', 'cycle')) or case['status'] == 'rejected':
            update_reopened_case(cur, case['id'], result, '重新计算')
        refresh_draft(cur, payload.period, payload.contract_id)
        cur.execute(case_sql, params)
        case = cur.fetchone()
        record_action(cur, user['sub'], 'calculate_reconciliation', 'reconciliation_case', case['id'], f"{case['difference_rate']}%")
        return case


@router.get("/cases")
def list_cases(user=Depends(current_user)):
    with db_cursor() as cur:
        cur.execute("""SELECT r.*, s.source_code, s.name AS source_name, c.metric_name, c.version, c.tolerance_pct
                       FROM reconciliation_cases r JOIN meter_sources s ON s.id=r.source_id JOIN metric_contracts c ON c.id=r.contract_id
                       ORDER BY r.period DESC, r.id DESC""")
        return cur.fetchall()


@router.post("/cases/{case_id}/review")
def review(case_id: int, payload: ReviewIn, user=Depends(require_roles("reviewer", "manager"))):
    with db_cursor() as cur:
        cur.execute("SELECT period FROM reconciliation_cases WHERE id=%s", (case_id,))
        initial = cur.fetchone()
        if not initial:
            raise HTTPException(404, detail="差异复核单不存在")
    with db_cursor(commit=True) as cur:
        lock_period(cur, initial['period'])
        cur.execute("SELECT * FROM reconciliation_cases WHERE id=%s", (case_id,))
        case = cur.fetchone()
        ensure_case_period_editable(cur, case['period'], case['contract_id'])
        if payload.action == 'close' and case['status'] not in {'confirmed', 'open'}:
            raise HTTPException(409, detail="只有待处理或已确认的复核单可以关闭")
        status = {'confirm': 'confirmed', 'reject': 'rejected', 'close': 'closed'}[payload.action]
        cur.execute("""UPDATE reconciliation_cases SET status=%s,issue_note=%s,reviewed_by=%s,reviewed_at=NOW(),
                       closed_at=IF(%s='closed',NOW(),NULL) WHERE id=%s""",
                    (status, payload.note or case['issue_note'], user['sub'], status, case_id))
        record_action(cur, user['sub'], f'review_{payload.action}', 'reconciliation_case', case_id, payload.note)
        cur.execute("SELECT * FROM reconciliation_cases WHERE id=%s", (case_id,))
        return cur.fetchone()
