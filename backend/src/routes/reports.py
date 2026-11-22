from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from ..closing_schemas import Period
from ..db import db_cursor, lock_period
from ..security import current_user, require_roles
from ..services.audit import record_action
from ..services.bill_close import freeze_bills
from ..services.budgets import aggregate_totals, freeze_budgets
from ..services.corrections import has_pending_corrections

router = APIRouter(prefix="/reports", tags=["reports"])


class PublishIn(BaseModel):
    period: Period
    contract_id: int = Field(gt=0)


def report_for_period(cur, period):
    cur.execute("SELECT * FROM monthly_reports WHERE period=%s", (period,))
    return cur.fetchone()


def assert_same_contract(report, contract_id):
    if report and report['contract_id'] != contract_id:
        raise HTTPException(409, detail="该周期已绑定另一指标版本")


@router.get("")
def list_reports(user=Depends(current_user)):
    with db_cursor() as cur:
        cur.execute("""SELECT r.*, c.metric_name, c.version FROM monthly_reports r
                       JOIN metric_contracts c ON c.id=r.contract_id ORDER BY r.period DESC""")
        return cur.fetchall()


@router.post("/draft")
def make_draft(payload: PublishIn, user=Depends(require_roles("analyst", "manager"))):
    with db_cursor(commit=True) as cur:
        lock_period(cur, payload.period)
        report = report_for_period(cur, payload.period)
        assert_same_contract(report, payload.contract_id)
        if report and report['status'] == 'published':
            raise HTTPException(409, detail="月报已签发，不能重新生成")
        cur.execute("SELECT id FROM metric_contracts WHERE id=%s", (payload.contract_id,))
        if not cur.fetchone():
            raise HTTPException(404, detail="指标版本不存在")
        totals = aggregate_totals(cur, payload.period, payload.contract_id)
        cur.execute("""INSERT INTO monthly_reports(period,contract_id,actual_kwh,expected_kwh,difference_rate,case_count,status)
                      VALUES(%s,%s,%s,%s,%s,%s,'draft') ON DUPLICATE KEY UPDATE actual_kwh=VALUES(actual_kwh),
                      expected_kwh=VALUES(expected_kwh), difference_rate=VALUES(difference_rate), case_count=VALUES(case_count)""",
                    (payload.period, payload.contract_id, *totals))
        return report_for_period(cur, payload.period)


@router.post("/publish")
def publish(payload: PublishIn, user=Depends(require_roles("manager"))):
    with db_cursor(commit=True) as cur:
        lock_period(cur, payload.period)
        cur.execute("SELECT * FROM metric_contracts WHERE id=%s", (payload.contract_id,))
        contract = cur.fetchone()
        if not contract:
            raise HTTPException(404, detail="指标版本不存在")
        report = report_for_period(cur, payload.period)
        if not report:
            raise HTTPException(409, detail="请先生成月报草稿")
        assert_same_contract(report, payload.contract_id)
        if report['status'] == 'published':
            return report
        cur.execute("SELECT * FROM reconciliation_cases WHERE period=%s AND contract_id=%s", (payload.period, payload.contract_id))
        cases = cur.fetchall()
        if not cases:
            raise HTTPException(409, detail="没有差异复核单，不能发布")
        if has_pending_corrections(cur, payload.period, payload.contract_id):
            raise HTTPException(409, detail="本月报涉及待复核抄表更正单，不能发布")
        if any(c["unit"] != contract["unit"] or c["cycle"] != contract["cycle"] for c in cases):
            raise HTTPException(422, detail="存在单位或周期不兼容的复核单，拒绝发布")
        if any(c["status"] != "closed" for c in cases):
            raise HTTPException(409, detail="全部差异复核单关闭后才可归档发布")
        freeze_budgets(cur, report)
        freeze_bills(cur, report)
        totals = aggregate_totals(cur, payload.period, payload.contract_id)
        cur.execute("""UPDATE monthly_reports SET actual_kwh=%s,expected_kwh=%s,difference_rate=%s,case_count=%s,
                       status='published',published_by=%s,published_at=NOW() WHERE id=%s""",
                    (*totals, user['sub'], report['id']))
        record_action(cur, user['sub'], 'publish_monthly_report', 'monthly_report', report['id'], payload.period)
        return report_for_period(cur, payload.period)
