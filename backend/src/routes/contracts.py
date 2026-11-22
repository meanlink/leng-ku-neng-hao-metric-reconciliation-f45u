from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from ..db import db_cursor
from ..security import current_user, require_roles
from ..services.audit import log_action

router = APIRouter(prefix="/contracts", tags=["contracts"])
class ContractIn(BaseModel):
    metric_code: str
    metric_name: str
    version: str
    unit: str = "kWh"
    cycle: str = "monthly"
    baseline_kwh_per_ton_day: float
    tolerance_pct: float = 5
    effective_from: str

class MappingIn(BaseModel):
    source_id: int
    contract_id: int
    mapped_unit: str
    mapped_cycle: str
    factor: float = 1
    note: str = ""

@router.get("")
def list_contracts(user=Depends(current_user)):
    with db_cursor() as cur:
        cur.execute("SELECT * FROM metric_contracts ORDER BY effective_from DESC, id DESC")
        return cur.fetchall()

@router.post("")
def create_contract(payload: ContractIn, user=Depends(require_roles("analyst", "manager"))):
    with db_cursor(commit=True) as cur:
        try:
            cur.execute("INSERT INTO metric_contracts(metric_code,metric_name,version,unit,cycle,baseline_kwh_per_ton_day,tolerance_pct,effective_from) VALUES(%s,%s,%s,%s,%s,%s,%s,%s)", tuple(payload.model_dump().values()))
            new_id = cur.lastrowid
        except Exception as exc:
            raise HTTPException(409, detail="指标编码与版本不能重复") from exc
    log_action(user["sub"], "create_contract", "metric_contract", new_id, payload.metric_name)
    return {"id": new_id, **payload.model_dump(), "status": "draft"}

@router.post("/mappings")
def create_mapping(payload: MappingIn, user=Depends(require_roles("analyst", "manager"))):
    with db_cursor() as cur:
        cur.execute("SELECT id FROM meter_sources WHERE id=%s", (payload.source_id,))
        if not cur.fetchone(): raise HTTPException(404, detail="电表来源不存在")
        cur.execute("SELECT id FROM metric_contracts WHERE id=%s", (payload.contract_id,))
        if not cur.fetchone(): raise HTTPException(404, detail="指标版本不存在")
    with db_cursor(commit=True) as cur:
        try:
            cur.execute("INSERT INTO source_mappings(source_id,contract_id,mapped_unit,mapped_cycle,factor,note) VALUES(%s,%s,%s,%s,%s,%s)", tuple(payload.model_dump().values()))
            new_id = cur.lastrowid
        except Exception as exc:
            raise HTTPException(409, detail="该来源与指标版本已存在映射") from exc
    log_action(user["sub"], "create_mapping", "source_mapping", new_id, payload.note)
    return {"id": new_id, **payload.model_dump(), "status": "active"}

@router.get("/mappings")
def list_mappings(user=Depends(current_user)):
    with db_cursor() as cur:
        cur.execute("SELECT m.*, s.source_code, s.name AS source_name, c.metric_code, c.version FROM source_mappings m JOIN meter_sources s ON s.id=m.source_id JOIN metric_contracts c ON c.id=m.contract_id ORDER BY m.id")
        return cur.fetchall()
