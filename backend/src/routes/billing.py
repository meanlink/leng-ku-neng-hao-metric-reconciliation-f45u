from contextlib import contextmanager

from fastapi import APIRouter, Depends

from ..billing_schemas import BillDecision, BillIn, TariffIn
from ..db import db_cursor, lock_period
from ..security import current_user, require_roles
from ..services.bill_close import billing_sheet
from ..services.bill_review import review_bill, submit_bill
from ..services.budgets import report_by_id, report_period
from ..services.tariffs import add_tariff

router = APIRouter(prefix='/utility-billing', tags=['供应商账单核验'])


@contextmanager
def billing_transaction(report_id):
    period = report_period(report_id)
    with db_cursor(commit=True) as cur:
        lock_period(cur, period)
        yield cur, report_by_id(cur, report_id)


@router.get('/{report_id}')
def read_sheet(report_id: int, user=Depends(current_user)):
    with db_cursor(commit=True) as cur:
        return billing_sheet(cur, report_by_id(cur, report_id))


@router.post('/{report_id}/tariffs', status_code=201)
def create_tariff(report_id: int, payload: TariffIn, user=Depends(require_roles('manager'))):
    with billing_transaction(report_id) as (cur, report):
        return add_tariff(cur, report, payload, user['sub'])


@router.post('/{report_id}/invoices', status_code=201)
def file_invoice(report_id: int, payload: BillIn, user=Depends(require_roles('analyst', 'manager'))):
    with billing_transaction(report_id) as (cur, report):
        return submit_bill(cur, report, payload, user['sub'])


@router.post('/{report_id}/invoices/{bill_id}/decision')
def decide_invoice(report_id: int, bill_id: int, payload: BillDecision,
                   user=Depends(require_roles('reviewer', 'manager'))):
    with billing_transaction(report_id) as (cur, report):
        return review_bill(cur, report, bill_id, payload, user['sub'])
