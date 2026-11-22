import time
from contextlib import contextmanager
import pymysql
from .billing_schema import BILLING_SCHEMA
from .config import MYSQL

SCHEMA = [
    """CREATE TABLE IF NOT EXISTS users (
      id INT PRIMARY KEY AUTO_INCREMENT, email VARCHAR(160) UNIQUE NOT NULL,
      name VARCHAR(80) NOT NULL, role VARCHAR(32) NOT NULL, password_hash CHAR(64) NOT NULL,
      created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    ) ENGINE=InnoDB""",
    """CREATE TABLE IF NOT EXISTS meter_sources (
      id INT PRIMARY KEY AUTO_INCREMENT, source_code VARCHAR(40) UNIQUE NOT NULL,
      name VARCHAR(120) NOT NULL, site VARCHAR(120) NOT NULL, unit VARCHAR(24) NOT NULL,
      cycle VARCHAR(24) NOT NULL, source_type VARCHAR(32) NOT NULL, status VARCHAR(24) NOT NULL DEFAULT 'active',
      last_reading DECIMAL(12,2) DEFAULT 0, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    ) ENGINE=InnoDB""",
    """CREATE TABLE IF NOT EXISTS metric_contracts (
      id INT PRIMARY KEY AUTO_INCREMENT, metric_code VARCHAR(40) NOT NULL, metric_name VARCHAR(120) NOT NULL,
      version VARCHAR(20) NOT NULL, unit VARCHAR(24) NOT NULL, cycle VARCHAR(24) NOT NULL,
      baseline_kwh_per_ton_day DECIMAL(12,4) NOT NULL, tolerance_pct DECIMAL(8,3) NOT NULL DEFAULT 5,
      status VARCHAR(24) NOT NULL DEFAULT 'draft', effective_from DATE NOT NULL,
      UNIQUE KEY uq_metric_version(metric_code, version)
    ) ENGINE=InnoDB""",
    """CREATE TABLE IF NOT EXISTS source_mappings (
      id INT PRIMARY KEY AUTO_INCREMENT, source_id INT NOT NULL, contract_id INT NOT NULL,
      mapped_unit VARCHAR(24) NOT NULL, mapped_cycle VARCHAR(24) NOT NULL, factor DECIMAL(12,6) NOT NULL DEFAULT 1,
      status VARCHAR(24) NOT NULL DEFAULT 'active', note VARCHAR(255),
      UNIQUE KEY uq_mapping(source_id, contract_id),
      FOREIGN KEY(source_id) REFERENCES meter_sources(id), FOREIGN KEY(contract_id) REFERENCES metric_contracts(id)
    ) ENGINE=InnoDB""",
    """CREATE TABLE IF NOT EXISTS meter_readings (
      id INT PRIMARY KEY AUTO_INCREMENT, source_id INT NOT NULL, period CHAR(7) NOT NULL,
      reading_date DATE NOT NULL, value DECIMAL(14,3) NOT NULL, unit VARCHAR(24) NOT NULL,
      cycle VARCHAR(24) NOT NULL, throughput_ton_day DECIMAL(14,3) NOT NULL,
      import_batch VARCHAR(60) NOT NULL, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
      UNIQUE KEY uq_reading(source_id, period, reading_date),
      FOREIGN KEY(source_id) REFERENCES meter_sources(id)
    ) ENGINE=InnoDB""",
    """CREATE TABLE IF NOT EXISTS reconciliation_cases (
      id INT PRIMARY KEY AUTO_INCREMENT, period CHAR(7) NOT NULL, source_id INT NOT NULL, contract_id INT NOT NULL,
      actual_kwh DECIMAL(14,3) NOT NULL, expected_kwh DECIMAL(14,3) NOT NULL,
      difference_kwh DECIMAL(14,3) NOT NULL, difference_rate DECIMAL(9,3) NOT NULL,
      unit VARCHAR(24) NOT NULL, cycle VARCHAR(24) NOT NULL,
      status VARCHAR(24) NOT NULL DEFAULT 'open', issue_note VARCHAR(500),
      reviewed_by INT NULL, reviewed_at DATETIME NULL, closed_at DATETIME NULL,
      UNIQUE KEY uq_case(period, source_id, contract_id),
      FOREIGN KEY(source_id) REFERENCES meter_sources(id), FOREIGN KEY(contract_id) REFERENCES metric_contracts(id),
      FOREIGN KEY(reviewed_by) REFERENCES users(id)
    ) ENGINE=InnoDB""",
    """CREATE TABLE IF NOT EXISTS monthly_reports (
      id INT PRIMARY KEY AUTO_INCREMENT, period CHAR(7) UNIQUE NOT NULL, contract_id INT NOT NULL,
      actual_kwh DECIMAL(14,3) NOT NULL, expected_kwh DECIMAL(14,3) NOT NULL, difference_rate DECIMAL(9,3) NOT NULL,
      case_count INT NOT NULL DEFAULT 0, status VARCHAR(24) NOT NULL DEFAULT 'draft',
      published_by INT NULL, published_at DATETIME NULL,
      FOREIGN KEY(contract_id) REFERENCES metric_contracts(id), FOREIGN KEY(published_by) REFERENCES users(id)
    ) ENGINE=InnoDB""",
    """CREATE TABLE IF NOT EXISTS audit_logs (
      id INT PRIMARY KEY AUTO_INCREMENT, user_id INT NULL, action VARCHAR(80) NOT NULL,
      entity VARCHAR(60) NOT NULL, entity_id VARCHAR(60), detail VARCHAR(500), created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    ) ENGINE=InnoDB""",
    """CREATE TABLE IF NOT EXISTS energy_period_locks (
      period CHAR(7) PRIMARY KEY
    ) ENGINE=InnoDB""",
    """CREATE TABLE IF NOT EXISTS reading_corrections (
      id INT PRIMARY KEY AUTO_INCREMENT, reading_id INT NOT NULL,
      corrected_value DECIMAL(14,3) NOT NULL, corrected_ton_days DECIMAL(14,3) NOT NULL,
      reason VARCHAR(24) NOT NULL, evidence VARCHAR(500) NOT NULL, status VARCHAR(16) NOT NULL DEFAULT 'pending',
      submitted_by INT NOT NULL, submitted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
      decided_by INT NULL, decided_at DATETIME NULL, decision_note VARCHAR(500),
      active_reading_id INT GENERATED ALWAYS AS (CASE WHEN status IN ('pending','approved') THEN reading_id END) STORED,
      UNIQUE KEY uq_active_correction(active_reading_id), KEY ix_correction_reading(reading_id),
      FOREIGN KEY(reading_id) REFERENCES meter_readings(id),
      FOREIGN KEY(submitted_by) REFERENCES users(id), FOREIGN KEY(decided_by) REFERENCES users(id),
      CONSTRAINT ck_correction_amounts CHECK (corrected_value >= 0 AND corrected_ton_days >= 0),
      CONSTRAINT ck_correction_reason CHECK (reason IN ('entry_error','meter_factor','throughput_recount')),
      CONSTRAINT ck_correction_state CHECK (
        (status='pending' AND decided_by IS NULL AND decided_at IS NULL AND decision_note IS NULL) OR
        (status IN ('approved','rejected') AND decided_by IS NOT NULL AND decided_at IS NOT NULL AND decision_note IS NOT NULL)
      )
    ) ENGINE=InnoDB""",
    """CREATE TABLE IF NOT EXISTS monthly_site_budgets (
      report_id INT NOT NULL, site VARCHAR(120) NOT NULL,
      budget_kwh DECIMAL(14,3) NOT NULL, rate_cny_per_kwh DECIMAL(8,4) NOT NULL,
      updated_by INT NOT NULL, updated_at DATETIME NOT NULL,
      frozen_actual_kwh DECIMAL(14,3) NULL, frozen_meter_count INT NULL,
      frozen_budget_cost DECIMAL(20,2) NULL, frozen_actual_cost DECIMAL(20,2) NULL,
      PRIMARY KEY(report_id, site), FOREIGN KEY(report_id) REFERENCES monthly_reports(id),
      FOREIGN KEY(updated_by) REFERENCES users(id),
      CONSTRAINT ck_positive_budget CHECK (budget_kwh > 0 AND rate_cny_per_kwh > 0),
      CONSTRAINT ck_budget_snapshot CHECK (
        (frozen_actual_kwh IS NULL AND frozen_meter_count IS NULL AND frozen_budget_cost IS NULL AND frozen_actual_cost IS NULL) OR
        (frozen_actual_kwh IS NOT NULL AND frozen_meter_count > 0 AND frozen_meter_count IS NOT NULL
         AND frozen_budget_cost IS NOT NULL AND frozen_actual_cost IS NOT NULL)
      )
    ) ENGINE=InnoDB""",
]


def lock_period(cur, period):
    # The upsert holds an exclusive row lock until the surrounding transaction ends.
    cur.execute("INSERT INTO energy_period_locks(period) VALUES(%s) ON DUPLICATE KEY UPDATE period=period", (period,))


def connect():
    last = None
    for _ in range(30):
        try:
            return pymysql.connect(**MYSQL, cursorclass=pymysql.cursors.DictCursor)
        except Exception as exc:
            last = exc
            time.sleep(1)
    raise last

@contextmanager
def db_cursor(commit=False):
    conn = connect()
    try:
        if commit:
            conn.begin()
        with conn.cursor() as cur:
            yield cur
        if commit:
            conn.commit()
    finally:
        conn.close()

def init_db():
    with db_cursor() as cur:
        for statement in (*SCHEMA, *BILLING_SCHEMA):
            cur.execute(statement)
