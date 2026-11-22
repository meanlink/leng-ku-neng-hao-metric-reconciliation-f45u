from src.billing_schemas import BillDecision, BillIn, CreditIn, TariffIn
from src.db import db_cursor
from src.routes.billing import create_tariff, decide_invoice, file_credit, file_invoice, read_sheet
from src.routes.reconcile import ReviewIn, RunIn, review, run
from src.routes.reports import PublishIn, make_draft, publish
from src.services.bill_math import calculate_charges
from src.services.bill_store import bill_history
from src.services.tariffs import latest_tariffs

PERIOD = '2027-01'
CREDIT_PERIOD = '2026-12'
SITE_CODES = ('MTR-HAI-01', 'MTR-HAI-03')
MAIN_SITE = '宁波北仑海风冷链园'
EAST_SITE = '东港周转冷库'
TARIFFS = {
    MAIN_SITE: dict(energy_rate='0.8200', demand_rate='36.0000', minimum_kw=180, fixed_fee=120),
    EAST_SITE: dict(energy_rate='0.7600', demand_rate=0, minimum_kw=0, fixed_fee=60),
}


def load_context():
    with db_cursor() as cur:
        cur.execute('SELECT id AS sub, role FROM users')
        users = {row['role']: row for row in cur.fetchall()}
        cur.execute('SELECT id FROM metric_contracts WHERE metric_code=%s AND version=%s', ('CS-EUI', 'v2026.10'))
        contract = cur.fetchone()['id']
        cur.execute('SELECT id, source_code, site FROM meter_sources WHERE source_code IN (%s, %s)', SITE_CODES)
        sources = {row['source_code']: row for row in cur.fetchall()}
    return users, contract, sources


def ensure_draft(users, contract, sources, period, readings):
    with db_cursor(commit=True) as cur:
        cur.execute('SELECT * FROM monthly_reports WHERE period=%s', (period,))
        report = cur.fetchone()
        if report:
            return report
        day = '28' if period.endswith('02') else '31'
        for code, value, ton_days in readings:
            cur.execute('''INSERT IGNORE INTO meter_readings(source_id,period,reading_date,value,unit,cycle,
                               throughput_ton_day,import_batch) VALUES(%s,%s,%s,%s,'kWh','monthly',%s,%s)''',
                        (sources[code]['id'], period, f'{period}-{day}', value, ton_days, f'{period}-meter-export'))
    for code, _, _ in readings:
        case = run(RunIn(period=period, contract_id=contract, source_id=sources[code]['id']), users['analyst'])
        if case['status'] != 'closed':
            review(case['id'], ReviewIn(action='close', note=f'{period} 电表导出与出入库吨日已核对。'),
                   users['reviewer'])
    return make_draft(PublishIn(period=period, contract_id=contract), users['analyst'])


def ensure_tariffs(report, users, contract_refs):
    with db_cursor() as cur:
        existing = latest_tariffs(cur, report['id'])
    for site, ref in contract_refs.items():
        if site not in existing:
            create_tariff(report['id'], TariffIn(site=site, contract_ref=ref, charge_tolerance=2, **TARIFFS[site]),
                          users['manager'])


def publish_with_bills(users, contract, report, specs, note):
    """File, approve and publish each site's bill so the values freeze."""
    with db_cursor() as cur:
        histories = bill_history(cur, report['id'])
    for site, spec in specs.items():
        if site in histories:
            continue
        file_invoice(report['id'], BillIn(site=site, evidence=f'{spec["invoice_number"]} 供电账单，与电表导出一致。',
                     **spec), users['analyst'])
    sheet = read_sheet(report['id'], users['manager'])
    for row in sheet['sites']:
        bill = row['history'][0]
        if bill['status'] == 'pending':
            decide_invoice(report['id'], bill['id'], BillDecision(decision='approved', note=note), users['reviewer'])
    return publish(PublishIn(period=report['period'], contract_id=contract), users['manager'])


def seed_billing():
    users, contract, sources = load_context()
    december = ensure_draft(users, contract, sources, CREDIT_PERIOD,
                            [('MTR-HAI-01', 11900, 6700), ('MTR-HAI-03', 6150, 3550)])
    ensure_tariffs(december, users, {MAIN_SITE: 'BL-2026-12-A', EAST_SITE: 'DG-2026-12-B'})
    if december['status'] != 'published':
        sheet = read_sheet(december['id'], users['manager'])
        refs = {MAIN_SITE: 'BL-2612-011', EAST_SITE: 'DG-2612-006'}
        specs = {}
        for row in sheet['sites']:
            charges = calculate_charges(row['actual_kwh'], row['tariff']['minimum_kw'], row['tariff'])
            specs[row['site']] = dict(invoice_number=refs[row['site']],
                                      invoiced_kwh=row['actual_kwh'],
                                      observed_peak_kw=row['tariff']['minimum_kw'],
                                      invoiced_demand_kw=charges['expected_demand_kw'],
                                      invoice_subtotal=charges['expected_subtotal'])
        december = publish_with_bills(users, contract, december, specs, '十二月账单已核对。')
    seed_credit_note(users, december)

    january = ensure_draft(users, contract, sources, PERIOD,
                           [('MTR-HAI-01', 12000, 6800), ('MTR-HAI-03', 6200, 3600)])
    if january['status'] == 'published':
        return
    ensure_tariffs(january, users, {MAIN_SITE: 'BL-2027-01-A', EAST_SITE: 'DG-2027-01-B'})
    with db_cursor() as cur:
        histories = bill_history(cur, january['id'])
    if MAIN_SITE not in histories:
        file_invoice(january['id'], BillIn(site=MAIN_SITE, invoice_number='BL-2701-017', invoiced_kwh=12000,
                     observed_peak_kw=169, invoiced_demand_kw=200, invoice_subtotal=17160,
                     evidence='BL-2701-017.pdf 第 2 页。最大需量记录显示 169 kW，账单计费栏为 200 kW。'),
                     users['analyst'])
    print('billing seed ok: January 2027 draft with pending 720 CNY exception, December frozen bill, '
          'credit note CR-2612-03 (600 CNY)')


def seed_credit_note(users, december):
    sheet = read_sheet(december['id'], users['manager'])
    main = next(row for row in sheet['sites'] if row['site'] == MAIN_SITE)
    if main['credit']['credits'] or not main['credit']['origin_bills']:
        return
    origin = main['credit']['origin_bills'][0]
    file_credit(december['id'], CreditIn(site=MAIN_SITE, credit_number='CR-2612-03', origin_bill_id=origin['id'],
                amount=600, evidence='供应商贷项单 CR-2612-03，十二月需量计费差额调整，可在后续同站账单抵扣。'),
                users['analyst'])
