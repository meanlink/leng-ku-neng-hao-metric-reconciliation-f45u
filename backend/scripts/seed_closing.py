from src.closing_schemas import CorrectionIn, SiteBudgetIn
from src.db import db_cursor
from src.routes.energy_close import set_budget, submit_correction
from src.routes.reconcile import ReviewIn, RunIn, review, run
from src.routes.reports import PublishIn, make_draft

PERIOD = '2026-10'


def seed_closing():
    with db_cursor(commit=True) as cur:
        cur.execute("SELECT id,role FROM users")
        users = {row['role']: {'sub': row['id']} for row in cur.fetchall()}
        cur.execute("SELECT id FROM meter_sources WHERE source_code='MTR-HAI-01'")
        main_id = cur.fetchone()['id']
        cur.execute("SELECT id FROM metric_contracts WHERE metric_code='CS-EUI' AND version='v2026.10'")
        contract_id = cur.fetchone()['id']
        cur.execute("""INSERT IGNORE INTO meter_sources(source_code,name,site,unit,cycle,source_type,status,last_reading)
                       VALUES('MTR-HAI-03','东港周转库总表','东港周转冷库','kWh','monthly','smart_meter','active',6500)""")
        cur.execute("SELECT id FROM meter_sources WHERE source_code='MTR-HAI-03'")
        second_id = cur.fetchone()['id']
        cur.execute("""INSERT IGNORE INTO source_mappings(source_id,contract_id,mapped_unit,mapped_cycle,factor,note)
                       VALUES(%s,%s,'kWh','monthly',1,'东港周转冷库总表映射')""", (second_id, contract_id))
        cur.execute("""INSERT IGNORE INTO meter_readings(source_id,period,reading_date,value,unit,cycle,throughput_ton_day,import_batch)
                       VALUES(%s,'2026-10','2026-10-31',6500,'kWh','monthly',2820,'seed-donggang-2026-10')""", (second_id,))
        cur.execute("SELECT id FROM meter_readings WHERE source_id=%s AND reading_date='2026-10-31'", (main_id,))
        reading_id = cur.fetchone()['id']
        cur.execute("SELECT * FROM monthly_reports WHERE period=%s", (PERIOD,))
        report = cur.fetchone()
    # The demonstration uses a distinct reading batch and never resets workflow states.
    if not report:
        for source_id in (main_id, second_id):
            case = run(RunIn(period=PERIOD, source_id=source_id, contract_id=contract_id), users['analyst'])
            if case['status'] != 'closed':
                review(case['id'], ReviewIn(action='close', note='现场读数及吞吐台账已核对。'), users['reviewer'])
        report = make_draft(PublishIn(period=PERIOD, contract_id=contract_id), users['analyst'])
    if report['status'] == 'draft':
        with db_cursor() as cur:
            cur.execute("SELECT id FROM reading_corrections WHERE reading_id=%s LIMIT 1", (reading_id,))
            has_correction = cur.fetchone()
            cur.execute("SELECT 1 FROM monthly_site_budgets WHERE report_id=%s LIMIT 1", (report['id'],))
            has_budget = cur.fetchone()
        if not has_correction:
            submit_correction(CorrectionIn(
                reading_id=reading_id, reason='meter_factor', corrected_value=4100, corrected_ton_days=870,
                evidence='工单 HF-1026，月底电表倍率复核确认应计 4,100 kWh。',
            ), users['analyst'])
        if not has_budget:
            set_budget(report['id'], SiteBudgetIn(site='宁波北仑海风冷链园', budget_kwh=12200, rate_cny_per_kwh='0.82'), users['analyst'])
    print('closing seed ok: MTR-HAI-01 correction 4440 -> 4100, 2 sites, October draft')
