from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from ..db import db_cursor, lock_period
from ..security import current_user, require_roles
from ..services.audit import log_action, record_action
from ..services.corrections import recalculate_source_cases

router = APIRouter(prefix="/sources", tags=["sources"])
class SourceIn(BaseModel):
    source_code: str
    name: str
    site: str
    unit: str = "kWh"
    cycle: str = "monthly"
    source_type: str = "smart_meter"

@router.get("")
def list_sources(user=Depends(current_user)):
    with db_cursor() as cur:
        cur.execute("SELECT * FROM meter_sources ORDER BY id")
        return cur.fetchall()

@router.post("")
def create_source(payload: SourceIn, user=Depends(require_roles("analyst", "manager"))):
    with db_cursor(commit=True) as cur:
        try:
            cur.execute("INSERT INTO meter_sources(source_code,name,site,unit,cycle,source_type) VALUES(%s,%s,%s,%s,%s,%s)", tuple(payload.model_dump().values()))
            new_id = cur.lastrowid
        except Exception as exc:
            raise HTTPException(409, detail="来源编码已存在或字段不符合约束") from exc
    log_action(user["sub"], "create_source", "meter_source", new_id, payload.name)
    return {"id": new_id, **payload.model_dump(), "status": "active"}

@router.post("/{source_id}/readings")
def add_reading(source_id: int, payload: dict, user=Depends(require_roles("analyst", "manager"))):
    required = ["period", "reading_date", "value", "unit", "cycle", "throughput_ton_day"]
    if any(key not in payload for key in required):
        raise HTTPException(422, detail="抄表记录缺少字段")
    with db_cursor(commit=True) as cur:
        lock_period(cur, payload['period'])
        cur.execute("SELECT * FROM meter_sources WHERE id=%s", (source_id,))
        source = cur.fetchone()
        if not source:
            raise HTTPException(404, detail="电表来源不存在")
        if source["unit"] != payload["unit"] or source["cycle"] != payload["cycle"]:
            raise HTTPException(422, detail="抄表单位或周期与来源契约不兼容")
        cur.execute("""SELECT r.id FROM monthly_reports r JOIN reconciliation_cases c
                       ON c.period=r.period AND c.contract_id=r.contract_id
                       WHERE r.period=%s AND c.source_id=%s AND r.status='published'""", (payload['period'], source_id))
        if cur.fetchone():
            raise HTTPException(409, detail="电表已纳入已签发月报，不能补录抄表")
        try:
            cur.execute("INSERT INTO meter_readings(source_id,period,reading_date,value,unit,cycle,throughput_ton_day,import_batch) VALUES(%s,%s,%s,%s,%s,%s,%s,%s)", (source_id, payload["period"], payload["reading_date"], payload["value"], payload["unit"], payload["cycle"], payload["throughput_ton_day"], payload.get("import_batch", "manual-entry")))
        except Exception as exc:
            raise HTTPException(409, detail="同来源同周期同日期的抄表记录已存在") from exc
        reading_id = cur.lastrowid
        cur.execute("UPDATE meter_sources SET last_reading=%s WHERE id=%s", (payload["value"], source_id))
        recalculate_source_cases(cur, {'period': payload['period'], 'source_id': source_id}, '新增抄表，重新复核')
        record_action(cur, user['sub'], 'add_reading', 'meter_reading', reading_id, f"{payload['period']} {payload['value']}")
    return {"id": reading_id, "status": "recorded"}

@router.get("/{source_id}/readings")
def list_readings(source_id: int, user=Depends(current_user)):
    with db_cursor() as cur:
        cur.execute("""SELECT r.*, c.id AS correction_id, c.status AS correction_status,
                       COALESCE(IF(c.status='approved',c.corrected_value,NULL),r.value) AS effective_value,
                       COALESCE(IF(c.status='approved',c.corrected_ton_days,NULL),r.throughput_ton_day) AS effective_ton_days
                       FROM meter_readings r LEFT JOIN reading_corrections c ON c.active_reading_id=r.id
                       WHERE r.source_id=%s ORDER BY r.reading_date DESC""", (source_id,))
        return cur.fetchall()
