from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, Field, StringConstraints

from .closing_schemas import Evidence, Quantity

Site = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]
Rate = Annotated[Decimal, Field(ge=0, max_digits=8, decimal_places=4)]
Demand = Annotated[Decimal, Field(ge=0, max_digits=10, decimal_places=3)]
Subtotal = Annotated[Decimal, Field(ge=0, max_digits=20, decimal_places=2)]


class TariffIn(BaseModel):
    site: Site
    contract_ref: Annotated[str, StringConstraints(strip_whitespace=True, min_length=4, max_length=100)]
    energy_rate: Rate = Field(gt=0)
    demand_rate: Rate
    minimum_kw: Demand
    fixed_fee: Decimal = Field(ge=0, max_digits=12, decimal_places=2)
    charge_tolerance: Decimal = Field(ge=0, max_digits=10, decimal_places=2)


class BillIn(BaseModel):
    site: Site
    invoice_number: Annotated[str, StringConstraints(strip_whitespace=True, min_length=4, max_length=80)]
    evidence: Evidence
    invoiced_kwh: Quantity
    observed_peak_kw: Demand
    invoiced_demand_kw: Demand
    invoice_subtotal: Subtotal


class BillDecision(BaseModel):
    decision: Literal['approved', 'returned']
    note: Evidence
