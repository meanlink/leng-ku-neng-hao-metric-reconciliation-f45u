from decimal import Decimal, ROUND_HALF_UP

from fastapi import HTTPException


def quant(value):
    return value.quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)


def validate_compatibility(source, contract, mapping):
    problems = []
    if source["unit"] != mapping["mapped_unit"] or contract["unit"] != mapping["mapped_unit"]:
        problems.append(f"单位不兼容：来源 {source['unit']} / 映射 {mapping['mapped_unit']} / 指标 {contract['unit']}")
    if source["cycle"] != mapping["mapped_cycle"] or contract["cycle"] != mapping["mapped_cycle"]:
        problems.append(f"周期不兼容：来源 {source['cycle']} / 映射 {mapping['mapped_cycle']} / 指标 {contract['cycle']}")
    return problems


def calculate_case(cur, period: str, source_id: int, contract_id: int):
    cur.execute("SELECT * FROM meter_sources WHERE id=%s", (source_id,))
    source = cur.fetchone()
    cur.execute("SELECT * FROM metric_contracts WHERE id=%s", (contract_id,))
    contract = cur.fetchone()
    cur.execute("SELECT * FROM source_mappings WHERE source_id=%s AND contract_id=%s", (source_id, contract_id))
    mapping = cur.fetchone()
    if not source or not contract or not mapping:
        raise HTTPException(404, detail="来源、指标版本或映射不存在")
    problems = validate_compatibility(source, contract, mapping)
    if problems:
        raise HTTPException(422, detail="；".join(problems))
    cur.execute("""SELECT COALESCE(SUM(COALESCE(c.corrected_ton_days, r.throughput_ton_day)), 0) AS ton_days,
                   COALESCE(SUM(COALESCE(c.corrected_value, r.value)), 0) AS actual_kwh
                   FROM meter_readings r LEFT JOIN reading_corrections c
                     ON c.active_reading_id=r.id AND c.status='approved'
                   WHERE r.source_id=%s AND r.period=%s""", (source_id, period))
    aggregate = cur.fetchone()
    actual = aggregate["actual_kwh"] * mapping["factor"]
    expected = contract["baseline_kwh_per_ton_day"] * aggregate["ton_days"]
    difference = actual - expected
    rate = (difference / expected * 100) if expected else Decimal(0)
    return {"period": period, "source_id": source_id, "contract_id": contract_id,
            "actual_kwh": quant(actual), "expected_kwh": quant(expected),
            "difference_kwh": quant(difference), "difference_rate": quant(rate),
            "unit": contract["unit"], "cycle": contract["cycle"],
            "issue_note": "差异超过阈值，需复核" if abs(rate) > contract["tolerance_pct"] else "差异在阈值内"}


def update_reopened_case(cur, case_id, result, reason):
    cur.execute("""UPDATE reconciliation_cases SET actual_kwh=%s, expected_kwh=%s, difference_kwh=%s,
                   difference_rate=%s, unit=%s, cycle=%s, status='open', issue_note=%s,
                   reviewed_by=NULL, reviewed_at=NULL, closed_at=NULL WHERE id=%s""",
                (result['actual_kwh'], result['expected_kwh'], result['difference_kwh'], result['difference_rate'],
                 result['unit'], result['cycle'], f"{reason}。{result['issue_note']}", case_id))
