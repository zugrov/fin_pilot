CREATE TABLE budget_versions (
  id uuid PRIMARY KEY,
  tenant_id uuid NOT NULL,
  company_id uuid NOT NULL,
  name text NOT NULL,
  year integer NOT NULL,
  status text NOT NULL,
  basis text NOT NULL,
  approved_at timestamptz,
  created_by uuid NOT NULL,
  created_at timestamptz NOT NULL,
  updated_at timestamptz NOT NULL,
  CONSTRAINT budget_versions_tenant_id_uq UNIQUE (tenant_id, id),
  CONSTRAINT budget_versions_company_id_uq UNIQUE (tenant_id, company_id, id),
  CONSTRAINT budget_versions_company_fk
    FOREIGN KEY (tenant_id, company_id) REFERENCES companies (tenant_id, id),
  CONSTRAINT budget_versions_name_ck CHECK (length(btrim(name)) > 0),
  CONSTRAINT budget_versions_year_ck CHECK (year BETWEEN 2000 AND 2100),
  CONSTRAINT budget_versions_status_ck CHECK (status IN ('draft', 'approved', 'archived')),
  CONSTRAINT budget_versions_basis_ck CHECK (basis IN ('cash', 'revenue')),
  CONSTRAINT budget_versions_approved_ck CHECK (
    (status = 'approved' AND approved_at IS NOT NULL)
    OR (status <> 'approved' AND approved_at IS NULL)
  )
);

CREATE UNIQUE INDEX uq_budget_approved
  ON budget_versions (tenant_id, company_id, year, basis)
  WHERE status = 'approved';

CREATE TABLE budget_lines (
  id uuid PRIMARY KEY,
  tenant_id uuid NOT NULL,
  company_id uuid NOT NULL,
  budget_version_id uuid NOT NULL,
  month integer NOT NULL,
  category_id uuid,
  direction_id uuid,
  metric_type text NOT NULL,
  amount numeric(20, 2) NOT NULL,
  distribution_method text NOT NULL,
  CONSTRAINT budget_lines_tenant_id_uq UNIQUE (tenant_id, id),
  CONSTRAINT budget_lines_version_fk
    FOREIGN KEY (tenant_id, budget_version_id)
    REFERENCES budget_versions (tenant_id, id),
  CONSTRAINT budget_lines_company_fk
    FOREIGN KEY (tenant_id, company_id) REFERENCES companies (tenant_id, id),
  CONSTRAINT budget_lines_category_fk
    FOREIGN KEY (tenant_id, category_id) REFERENCES cash_categories (tenant_id, id),
  CONSTRAINT budget_lines_direction_fk
    FOREIGN KEY (tenant_id, company_id, direction_id)
    REFERENCES directions (tenant_id, company_id, id),
  CONSTRAINT budget_lines_month_ck CHECK (month BETWEEN 1 AND 12),
  CONSTRAINT budget_lines_metric_ck
    CHECK (metric_type IN ('cash_in', 'cash_out', 'revenue')),
  CONSTRAINT budget_lines_amount_ck CHECK (amount >= 0),
  CONSTRAINT budget_lines_distribution_ck CHECK (distribution_method = 'calendar_days')
);

CREATE TABLE budget_daily_allocations (
  id uuid PRIMARY KEY,
  tenant_id uuid NOT NULL,
  line_id uuid NOT NULL,
  allocation_date date NOT NULL,
  amount numeric(20, 2) NOT NULL,
  CONSTRAINT budget_daily_allocations_day_uq UNIQUE (tenant_id, line_id, allocation_date),
  CONSTRAINT budget_daily_allocations_line_fk
    FOREIGN KEY (tenant_id, line_id) REFERENCES budget_lines (tenant_id, id),
  CONSTRAINT budget_daily_allocations_amount_ck CHECK (amount >= 0)
);

CREATE TABLE alert_rules (
  id uuid PRIMARY KEY,
  tenant_id uuid NOT NULL,
  company_id uuid NOT NULL,
  rule_type text NOT NULL,
  thresholds_json jsonb NOT NULL,
  severity text NOT NULL,
  enabled boolean NOT NULL DEFAULT true,
  cooldown_minutes integer NOT NULL,
  created_at timestamptz NOT NULL,
  updated_at timestamptz NOT NULL,
  CONSTRAINT alert_rules_tenant_id_uq UNIQUE (tenant_id, id),
  CONSTRAINT alert_rules_company_type_uq UNIQUE (tenant_id, company_id, rule_type),
  CONSTRAINT alert_rules_company_fk
    FOREIGN KEY (tenant_id, company_id) REFERENCES companies (tenant_id, id),
  CONSTRAINT alert_rules_type_ck CHECK (rule_type IN (
    'cash_gap', 'reserve_breach', 'expense_overrun', 'revenue_shortfall',
    'large_outgoing', 'unusual_outgoing', 'new_counterparty', 'duplicate_candidate',
    'stale_source', 'overdue_obligation', 'unclassified_share'
  )),
  CONSTRAINT alert_rules_severity_ck
    CHECK (severity IN ('critical', 'high', 'warning', 'info')),
  CONSTRAINT alert_rules_cooldown_ck CHECK (cooldown_minutes >= 0)
);

CREATE TABLE alerts (
  id uuid PRIMARY KEY,
  tenant_id uuid NOT NULL,
  company_id uuid NOT NULL,
  rule_type text NOT NULL,
  fingerprint text NOT NULL,
  severity text NOT NULL,
  status text NOT NULL,
  first_seen_at timestamptz NOT NULL,
  last_seen_at timestamptz NOT NULL,
  evidence_json jsonb NOT NULL,
  source_refs jsonb NOT NULL,
  resolved_at timestamptz,
  CONSTRAINT alerts_tenant_id_uq UNIQUE (tenant_id, id),
  CONSTRAINT alerts_fingerprint_uq UNIQUE (tenant_id, company_id, fingerprint),
  CONSTRAINT alerts_company_fk
    FOREIGN KEY (tenant_id, company_id) REFERENCES companies (tenant_id, id),
  CONSTRAINT alerts_type_ck CHECK (rule_type IN (
    'cash_gap', 'reserve_breach', 'expense_overrun', 'revenue_shortfall',
    'large_outgoing', 'unusual_outgoing', 'new_counterparty', 'duplicate_candidate',
    'stale_source', 'overdue_obligation', 'unclassified_share'
  )),
  CONSTRAINT alerts_severity_ck
    CHECK (severity IN ('critical', 'high', 'warning', 'info')),
  CONSTRAINT alerts_status_ck CHECK (status IN ('open', 'acknowledged', 'resolved')),
  CONSTRAINT alerts_resolved_ck CHECK (
    (status = 'resolved' AND resolved_at IS NOT NULL)
    OR (status <> 'resolved' AND resolved_at IS NULL)
  )
);

CREATE INDEX alerts_company_status ON alerts (tenant_id, company_id, status);

ALTER TABLE source_connections DROP CONSTRAINT source_connections_dataset_ck;
ALTER TABLE source_connections ADD CONSTRAINT source_connections_dataset_ck
  CHECK (dataset IN ('cash', 'revenue', 'plan', 'budget'));

ALTER TABLE source_identities DROP CONSTRAINT source_identities_target_ck;
ALTER TABLE source_identities ADD COLUMN budget_line_id uuid;
ALTER TABLE source_identities ADD CONSTRAINT source_identities_budget_fk
  FOREIGN KEY (tenant_id, budget_line_id) REFERENCES budget_lines (tenant_id, id);
ALTER TABLE source_identities ADD CONSTRAINT source_identities_target_ck CHECK (
  (
    entity_type = 'cash_transaction'
    AND canonical_entity_id IS NOT NULL
    AND revenue_entry_id IS NULL
    AND planned_event_id IS NULL
    AND budget_line_id IS NULL
  )
  OR (
    entity_type = 'revenue_entry'
    AND revenue_entry_id IS NOT NULL
    AND canonical_entity_id IS NULL
    AND planned_event_id IS NULL
    AND budget_line_id IS NULL
  )
  OR (
    entity_type = 'planned_event'
    AND planned_event_id IS NOT NULL
    AND canonical_entity_id IS NULL
    AND revenue_entry_id IS NULL
    AND budget_line_id IS NULL
  )
  OR (
    entity_type = 'budget_line'
    AND budget_line_id IS NOT NULL
    AND canonical_entity_id IS NULL
    AND revenue_entry_id IS NULL
    AND planned_event_id IS NULL
  )
);

ALTER TABLE budget_versions ENABLE ROW LEVEL SECURITY;
ALTER TABLE budget_versions FORCE ROW LEVEL SECURITY;
ALTER TABLE budget_lines ENABLE ROW LEVEL SECURITY;
ALTER TABLE budget_lines FORCE ROW LEVEL SECURITY;
ALTER TABLE budget_daily_allocations ENABLE ROW LEVEL SECURITY;
ALTER TABLE budget_daily_allocations FORCE ROW LEVEL SECURITY;
ALTER TABLE alert_rules ENABLE ROW LEVEL SECURITY;
ALTER TABLE alert_rules FORCE ROW LEVEL SECURITY;
ALTER TABLE alerts ENABLE ROW LEVEL SECURITY;
ALTER TABLE alerts FORCE ROW LEVEL SECURITY;

CREATE POLICY budget_versions_tenant ON budget_versions
  FOR ALL USING (tenant_id = app_tenant()) WITH CHECK (tenant_id = app_tenant());
CREATE POLICY budget_lines_tenant ON budget_lines
  FOR ALL USING (tenant_id = app_tenant()) WITH CHECK (tenant_id = app_tenant());
CREATE POLICY budget_daily_allocations_tenant ON budget_daily_allocations
  FOR ALL USING (tenant_id = app_tenant()) WITH CHECK (tenant_id = app_tenant());
CREATE POLICY alert_rules_tenant ON alert_rules
  FOR ALL USING (tenant_id = app_tenant()) WITH CHECK (tenant_id = app_tenant());
CREATE POLICY alerts_tenant ON alerts
  FOR ALL USING (tenant_id = app_tenant()) WITH CHECK (tenant_id = app_tenant());

GRANT SELECT, INSERT, UPDATE ON
  budget_versions, budget_lines, budget_daily_allocations, alert_rules, alerts
TO finpilot_app, finpilot_worker;
