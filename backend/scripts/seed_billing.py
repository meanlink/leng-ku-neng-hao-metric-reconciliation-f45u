from src.billing_schemas import BillIn, TariffIn
from src.db import db_cursor
from src.routes.billing import create_tariff, file_invoice
from src.routes.reconcile import ReviewIn, RunIn, review, run
from src.routes.reports import PublishIn, make_draft
from src.services.bill_store import bill_history
from src.services.tariffs import latest_tariffs

PERIOD = '2027-01'
SITE_CODES = ('MTR-HAI-01', 'MTR-HAI-03')


def seed_billing():
    with db_cursor(commit=True) as cur:
        cur.execute('SELECT id AS sub, role FROM users')
        users = {row['role']: row for row in cur.fetchall()}
        cur.execute('SELECT id FROM metric_contracts WHERE metric_code=%s AND version=%s', ('CS-EUI', 'v2026.10'))
        contract = cur.fetchone()['id']
        cur.execute('SELECT id, source_code, site FROM meter_sources WHERE source_code IN (%s, %s)', SITE_CODES)
        sources = {row['source_code']: row for row in cur.fetchall()}
        cur.execute('SELECT * FROM monthly_reports WHERE period=%s', (PERIOD,))
        report = cur.fetchone()
        if not report:
            for code, value, ton_days in zip(SITE_CODES, (12000, 6200), (6800, 3600)):
                cur.execute('''INSERT IGNORE INTO meter_readings(source_id,period,reading_date,value,unit,cycle,
                                   throughput_ton_day,import_batch) VALUES(%s,%s,'2027-01-31',%s,'kWh',
                                   'monthly',%s,'jan-close-meter-export-2027')''',
                            (sources[code]['id'], PERIOD, value, ton_days))
    if not report:
        for code in SITE_CODES:
            case = run(RunIn(period=PERIOD, contract_id=contract, source_id=sources[code]['id']), users['analyst'])
            if case['status'] != 'closed':
                review(case['id'], ReviewIn(action='close', note='已核对一月电表导出和出入库吨日。'), users['reviewer'])
        report = make_draft(PublishIn(period=PERIOD, contract_id=contract), users['analyst'])
    if report['status'] == 'published':
        return
    with db_cursor() as cur:
        tariffs = latest_tariffs(cur, report['id'])
        histories = bill_history(cur, report['id'])
    main_site, east_site = (sources[code]['site'] for code in SITE_CODES)
    examples = [
        TariffIn(site=main_site, contract_ref='BL-2027-01-A', energy_rate='0.8200', demand_rate='36.0000',
                 minimum_kw=180, fixed_fee=120, charge_tolerance=2),
        TariffIn(site=east_site, contract_ref='DG-2027-01-B', energy_rate='0.7600', demand_rate=0,
                 minimum_kw=0, fixed_fee=60, charge_tolerance=2),
    ]
    for tariff in examples:
        if tariff.site not in tariffs:
            create_tariff(report['id'], tariff, users['manager'])
    if main_site not in histories:
        file_invoice(report['id'], BillIn(site=main_site, invoice_number='BL-2701-017', invoiced_kwh=12000,
                     observed_peak_kw=169, invoiced_demand_kw=200, invoice_subtotal=17160,
                     evidence='BL-2701-017.pdf 第 2 页。最大需量记录显示 169 kW，账单计费栏为 200 kW。'), users['analyst'])
    print('billing seed ok: January 2027, 2 sites, tariff demand floor and pending 720 CNY exception')
