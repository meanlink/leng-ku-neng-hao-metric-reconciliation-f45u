BILLING_SCHEMA = [
    """CREATE TABLE IF NOT EXISTS site_tariffs (
      id INT PRIMARY KEY AUTO_INCREMENT, report_id INT NOT NULL, site VARCHAR(120) NOT NULL,
      revision INT NOT NULL, contract_ref VARCHAR(100) NOT NULL,
      energy_rate DECIMAL(8,4) NOT NULL, demand_rate DECIMAL(8,4) NOT NULL,
      minimum_kw DECIMAL(10,3) NOT NULL, fixed_fee DECIMAL(12,2) NOT NULL,
      charge_tolerance DECIMAL(10,2) NOT NULL, created_by INT NOT NULL,
      created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
      UNIQUE KEY uq_tariff_revision(report_id, site, revision),
      FOREIGN KEY(report_id) REFERENCES monthly_reports(id), FOREIGN KEY(created_by) REFERENCES users(id),
      CHECK (revision > 0 AND energy_rate > 0 AND demand_rate >= 0 AND minimum_kw >= 0
             AND fixed_fee >= 0 AND charge_tolerance >= 0)
    ) ENGINE=InnoDB""",
    """CREATE TABLE IF NOT EXISTS utility_bill_revisions (
      id INT PRIMARY KEY AUTO_INCREMENT, tariff_id INT NOT NULL, report_id INT NOT NULL,
      site VARCHAR(120) NOT NULL, revision INT NOT NULL, invoice_number VARCHAR(80) NOT NULL,
      evidence VARCHAR(500) NOT NULL, invoiced_kwh DECIMAL(14,3) NOT NULL,
      observed_peak_kw DECIMAL(10,3) NOT NULL, invoiced_demand_kw DECIMAL(10,3) NOT NULL,
      invoice_subtotal DECIMAL(20,2) NOT NULL, reconciled_kwh DECIMAL(14,3) NOT NULL,
      expected_demand_kw DECIMAL(10,3) NOT NULL, energy_charge DECIMAL(20,2) NOT NULL,
      demand_charge DECIMAL(20,2) NOT NULL, expected_subtotal DECIMAL(20,2) NOT NULL,
      status VARCHAR(16) NOT NULL DEFAULT 'pending', submitted_by INT NOT NULL,
      submitted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, reviewed_by INT NULL,
      reviewed_at DATETIME NULL, review_note VARCHAR(500) NULL, frozen_at DATETIME NULL,
      UNIQUE KEY uq_utility_revision(report_id, site, revision),
      KEY ix_utility_document(report_id, invoice_number),
      FOREIGN KEY(tariff_id) REFERENCES site_tariffs(id), FOREIGN KEY(report_id) REFERENCES monthly_reports(id),
      FOREIGN KEY(submitted_by) REFERENCES users(id), FOREIGN KEY(reviewed_by) REFERENCES users(id),
      CHECK (status IN ('pending', 'returned', 'approved')),
      CHECK ((status = 'pending' AND reviewed_by IS NULL AND reviewed_at IS NULL AND review_note IS NULL)
             OR (status <> 'pending' AND reviewed_by IS NOT NULL AND reviewed_by <> submitted_by
                 AND reviewed_at IS NOT NULL AND review_note IS NOT NULL)),
      CHECK (frozen_at IS NULL OR status = 'approved'),
      CHECK (revision > 0 AND invoiced_kwh >= 0 AND observed_peak_kw >= 0
             AND invoiced_demand_kw >= 0 AND invoice_subtotal >= 0 AND reconciled_kwh >= 0)
    ) ENGINE=InnoDB""",
]
