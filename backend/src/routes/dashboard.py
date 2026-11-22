from fastapi import APIRouter, Depends
from ..db import db_cursor
from ..security import current_user
router = APIRouter(prefix="/dashboard", tags=["dashboard"])
@router.get("")
def dashboard(user=Depends(current_user)):
    with db_cursor() as cur:
        cur.execute("SELECT COUNT(*) AS n FROM meter_sources WHERE status='active'"); sources = cur.fetchone()["n"]
        cur.execute("SELECT COUNT(*) AS n FROM reconciliation_cases WHERE status IN ('open','confirmed')"); open_cases = cur.fetchone()["n"]
        cur.execute("SELECT COUNT(*) AS n FROM reconciliation_cases WHERE status='closed'"); closed_cases = cur.fetchone()["n"]
        cur.execute("SELECT COUNT(*) AS n FROM monthly_reports WHERE status='published'"); published = cur.fetchone()["n"]
        cur.execute("SELECT * FROM reconciliation_cases ORDER BY period DESC, id DESC LIMIT 5"); recent = cur.fetchall()
    return {"sources": sources, "open_cases": open_cases, "closed_cases": closed_cases, "published_reports": published, "recent_cases": recent}
