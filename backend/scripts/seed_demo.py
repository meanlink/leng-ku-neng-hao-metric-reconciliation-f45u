import sys
from src.db import db_cursor, init_db
from src.security import hash_password

USERS = [
    ("analyst@haifeng.local", "林岚", "analyst"),
    ("reviewer@haifeng.local", "周衡", "reviewer"),
    ("manager@haifeng.local", "顾宁", "manager"),
]

def seed():
    init_db()
    with db_cursor(commit=True) as cur:
        for email, name, role in USERS:
            cur.execute("INSERT INTO users(email,name,role,password_hash) VALUES(%s,%s,%s,%s) ON DUPLICATE KEY UPDATE name=VALUES(name), role=VALUES(role), password_hash=VALUES(password_hash)", (email, name, role, hash_password("coldstore123")))
        cur.execute("INSERT INTO meter_sources(source_code,name,site,unit,cycle,source_type,status,last_reading) VALUES('MTR-HAI-01','海风一号冷库总表','宁波北仑海风冷链园','kWh','monthly','smart_meter','active',12840) ON DUPLICATE KEY UPDATE name=VALUES(name),last_reading=VALUES(last_reading)")
        cur.execute("SELECT id FROM meter_sources WHERE source_code='MTR-HAI-01'"); source_id = cur.fetchone()["id"]
        cur.execute("INSERT INTO meter_sources(source_code,name,site,unit,cycle,source_type,status,last_reading) VALUES('MTR-HAI-02','海风二号备用表','宁波北仑海风冷链园','kWh','monthly','manual_meter','active',6420) ON DUPLICATE KEY UPDATE name=VALUES(name),last_reading=VALUES(last_reading)")
        cur.execute("INSERT INTO metric_contracts(metric_code,metric_name,version,unit,cycle,baseline_kwh_per_ton_day,tolerance_pct,status,effective_from) VALUES('CS-EUI','单位吞吐能耗','v2026.10','kWh','monthly',1.68,5,'active','2026-10-01') ON DUPLICATE KEY UPDATE metric_name=VALUES(metric_name),baseline_kwh_per_ton_day=VALUES(baseline_kwh_per_ton_day)")
        cur.execute("SELECT id FROM metric_contracts WHERE metric_code='CS-EUI' AND version='v2026.10'"); contract_id = cur.fetchone()["id"]
        cur.execute("INSERT INTO source_mappings(source_id,contract_id,mapped_unit,mapped_cycle,factor,status,note) VALUES(%s,%s,'kWh','monthly',1,'active','海风园区月度总表映射') ON DUPLICATE KEY UPDATE factor=VALUES(factor),note=VALUES(note)", (source_id, contract_id))
        readings = [
            (source_id, '2026-10', '2026-10-10', 4120, 'kWh', 'monthly', 820),
            (source_id, '2026-10', '2026-10-20', 4280, 'kWh', 'monthly', 850),
            (source_id, '2026-10', '2026-10-31', 4440, 'kWh', 'monthly', 870),
        ]
        for row in readings:
            cur.execute("INSERT INTO meter_readings(source_id,period,reading_date,value,unit,cycle,throughput_ton_day,import_batch) VALUES(%s,%s,%s,%s,%s,%s,%s,'seed-oct-2026') ON DUPLICATE KEY UPDATE value=VALUES(value),throughput_ton_day=VALUES(throughput_ton_day)", row)
    print("seed ok: users=3, sources=2, contracts=1, mappings=1, readings=3")

if __name__ == '__main__':
    seed()
    if {'--with-expansion', '--with-billing'}.intersection(sys.argv[1:]):
        from .seed_closing import seed_closing
        seed_closing()
    if '--with-billing' in sys.argv[1:]:
        from .seed_billing import seed_billing
        seed_billing()
