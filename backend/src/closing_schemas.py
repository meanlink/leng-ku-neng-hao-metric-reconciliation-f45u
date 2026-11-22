from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, Field, StringConstraints

Period = Annotated[str, StringConstraints(pattern=r"^[0-9]{4}-(0[1-9]|1[0-2])$")]
Evidence = Annotated[str, StringConstraints(strip_whitespace=True, min_length=4, max_length=500)]
Quantity = Annotated[Decimal, Field(ge=0, max_digits=14, decimal_places=3)]


class CorrectionIn(BaseModel):
    reading_id: int = Field(gt=0)
    reason: Literal["entry_error", "meter_factor", "throughput_recount"]
    corrected_value: Quantity
    corrected_ton_days: Quantity
    evidence: Evidence


class CorrectionDecision(BaseModel):
    decision: Literal["approved", "rejected"]
    note: Evidence


class SiteBudgetIn(BaseModel):
    site: str = Field(min_length=1, max_length=120)
    budget_kwh: Quantity = Field(gt=0)
    rate_cny_per_kwh: Decimal = Field(gt=0, max_digits=8, decimal_places=4)
