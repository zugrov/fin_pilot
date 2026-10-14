CREATE TABLE recurrence_rules (
  id uuid PRIMARY KEY,
  tenant_id uuid NOT NULL,
  company_id uuid NOT NULL,
  frequency text NOT NULL,
  interval_count integer NOT NULL,
  day_of_month integer,
  start_date date NOT NULL,
  end_date date,
  month_end_policy text NOT NULL,
  direction text NOT NULL,
  amount numeric(20, 2) NOT NULL,
  currency text NOT NULL,
  confidence text NOT NULL,
  priority text NOT NULL,
  category_id uuid,
  wallet_id uuid,
  counterparty_id uuid,
  notes text NOT NULL DEFAULT '',
  created_at timestamptz NOT NULL,
  CONSTRAINT recurrence_rules_tenant_id_uq UNIQUE (tenant_id, id),
  CONSTRAINT recurrence_rules_company_fk
    FOREIGN KEY (tenant_id, company_id) REFERENCES companies (tenant_id, id),
  CONSTRAINT recurrence_rules_frequency_ck CHECK (frequency IN ('weekly', 'monthly')),
  CONSTRAINT recurrence_rules_interval_ck CHECK (interval_count >= 1),
  CONSTRAINT recurrence_rules_policy_ck CHECK (month_end_policy = 'last_day'),
  CONSTRAINT recurrence_rules_direction_ck CHECK (direction IN ('in', 'out')),
  CONSTRAINT recurrence_rules_amount_ck CHECK (amount > 0),
  CONSTRAINT recurrence_rules_currency_ck CHECK (currency = 'RUB'),
  CONSTRAINT recurrence_rules_confidence_ck
    CHECK (confidence IN ('confirmed', 'expected', 'tentative')),
  CONSTRAINT recurrence_rules_priority_ck
    CHECK (priority IN ('critical', 'high', 'normal', 'low')),
  CONSTRAINT recurrence_rules_day_ck CHECK (
    (frequency = 'weekly' AND day_of_month IS NULL)
    OR (frequency = 'monthly' AND day_of_month BETWEEN 1 AND 31)
  )
);

CREATE TABLE planned_cash_events (
  id uuid PRIMARY KEY,
  tenant_id uuid NOT NULL,
  company_id uuid NOT NULL,
  wallet_id uuid,
  direction text NOT NULL,
  amount numeric(20, 2) NOT NULL,
  currency text NOT NULL,
  category_id uuid,
  counterparty_id uuid,
  due_date date NOT NULL,
  expected_date date NOT NULL,
  confidence text NOT NULL,
  priority text NOT NULL,
  status text NOT NULL,
  recurrence_rule_id uuid,
  occurrence_key text,
  notes text NOT NULL DEFAULT '',
  version integer NOT NULL DEFAULT 1,
  source text NOT NULL,
  external_id text,
  source_connection_id uuid,
  import_batch_id uuid,
  created_by uuid NOT NULL,
  created_at timestamptz NOT NULL,
  updated_at timestamptz NOT NULL,
  CONSTRAINT planned_cash_events_tenant_id_uq UNIQUE (tenant_id, id),
  CONSTRAINT planned_cash_events_company_id_uq UNIQUE (tenant_id, company_id, id),
  CONSTRAINT planned_cash_events_company_fk
    FOREIGN KEY (tenant_id, company_id) REFERENCES companies (tenant_id, id),
  CONSTRAINT planned_cash_events_wallet_fk
    FOREIGN KEY (tenant_id, company_id, wallet_id)
    REFERENCES wallets (tenant_id, company_id, id),
  CONSTRAINT planned_cash_events_category_fk
    FOREIGN KEY (tenant_id, category_id) REFERENCES cash_categories (tenant_id, id),
  CONSTRAINT planned_cash_events_counterparty_fk
    FOREIGN KEY (tenant_id, company_id, counterparty_id)
    REFERENCES counterparties (tenant_id, company_id, id),
  CONSTRAINT planned_cash_events_rule_fk
    FOREIGN KEY (tenant_id, recurrence_rule_id) REFERENCES recurrence_rules (tenant_id, id),
  CONSTRAINT planned_cash_events_connection_fk
    FOREIGN KEY (tenant_id, source_connection_id)
    REFERENCES source_connections (tenant_id, id),
  CONSTRAINT planned_cash_events_batch_fk
    FOREIGN KEY (tenant_id, import_batch_id) REFERENCES import_batches (tenant_id, id),
  CONSTRAINT planned_cash_events_direction_ck CHECK (direction IN ('in', 'out')),
  CONSTRAINT planned_cash_events_amount_ck CHECK (amount > 0),
  CONSTRAINT planned_cash_events_currency_ck CHECK (currency = 'RUB'),
  CONSTRAINT planned_cash_events_confidence_ck
    CHECK (confidence IN ('confirmed', 'expected', 'tentative')),
  CONSTRAINT planned_cash_events_priority_ck
    CHECK (priority IN ('critical', 'high', 'normal', 'low')),
  CONSTRAINT planned_cash_events_status_ck
    CHECK (status IN ('planned', 'partially_paid', 'paid', 'cancelled')),
  CONSTRAINT planned_cash_events_source_ck CHECK (source IN ('manual', 'import'))
);

CREATE UNIQUE INDEX uq_planned_occurrence
  ON planned_cash_events (tenant_id, company_id, occurrence_key)
  WHERE occurrence_key IS NOT NULL;

CREATE INDEX planned_cash_events_expected
  ON planned_cash_events (tenant_id, company_id, expected_date)
  WHERE status <> 'cancelled';

CREATE TABLE payment_matches (
  id uuid PRIMARY KEY,
  tenant_id uuid NOT NULL,
  company_id uuid NOT NULL,
  event_id uuid NOT NULL,
  cash_transaction_id uuid NOT NULL,
  allocated_amount numeric(20, 2) NOT NULL,
  created_by uuid NOT NULL,
  created_at timestamptz NOT NULL,
  CONSTRAINT payment_matches_pair_uq UNIQUE (tenant_id, event_id, cash_transaction_id),
  CONSTRAINT payment_matches_company_fk
    FOREIGN KEY (tenant_id, company_id) REFERENCES companies (tenant_id, id),
  CONSTRAINT payment_matches_event_fk
    FOREIGN KEY (tenant_id, event_id) REFERENCES planned_cash_events (tenant_id, id),
  CONSTRAINT payment_matches_cash_fk
    FOREIGN KEY (tenant_id, cash_transaction_id)
    REFERENCES cash_transactions (tenant_id, id),
  CONSTRAINT payment_matches_amount_ck CHECK (allocated_amount > 0)
);

CREATE TABLE obligations (
  id uuid PRIMARY KEY,
  tenant_id uuid NOT NULL,
  company_id uuid NOT NULL,
  obligation_type text NOT NULL,
  counterparty_id uuid,
  document_ref text,
  issue_date date NOT NULL,
  due_date date NOT NULL,
  original_amount numeric(20, 2) NOT NULL,
  status text NOT NULL,
  created_by uuid NOT NULL,
  created_at timestamptz NOT NULL,
  CONSTRAINT obligations_tenant_id_uq UNIQUE (tenant_id, id),
  CONSTRAINT obligations_company_id_uq UNIQUE (tenant_id, company_id, id),
  CONSTRAINT obligations_company_fk
    FOREIGN KEY (tenant_id, company_id) REFERENCES companies (tenant_id, id),
  CONSTRAINT obligations_counterparty_fk
    FOREIGN KEY (tenant_id, company_id, counterparty_id)
    REFERENCES counterparties (tenant_id, company_id, id),
  CONSTRAINT obligations_type_ck CHECK (obligation_type IN ('receivable', 'payable')),
  CONSTRAINT obligations_status_ck CHECK (status IN ('open', 'settled', 'cancelled')),
  CONSTRAINT obligations_amount_ck CHECK (original_amount > 0)
);

CREATE TABLE obligation_cash_links (
  id uuid PRIMARY KEY,
  tenant_id uuid NOT NULL,
  company_id uuid NOT NULL,
  obligation_id uuid NOT NULL,
  event_id uuid NOT NULL,
  created_at timestamptz NOT NULL,
  CONSTRAINT obligation_cash_links_obligation_uq UNIQUE (tenant_id, obligation_id),
  CONSTRAINT obligation_cash_links_event_uq UNIQUE (tenant_id, event_id),
  CONSTRAINT obligation_cash_links_company_fk
    FOREIGN KEY (tenant_id, company_id) REFERENCES companies (tenant_id, id),
  CONSTRAINT obligation_cash_links_obligation_fk
    FOREIGN KEY (tenant_id, obligation_id) REFERENCES obligations (tenant_id, id),
  CONSTRAINT obligation_cash_links_event_fk
    FOREIGN KEY (tenant_id, event_id) REFERENCES planned_cash_events (tenant_id, id)
);

CREATE TABLE forecast_runs (
  id uuid PRIMARY KEY,
  tenant_id uuid NOT NULL,
  company_id uuid NOT NULL,
  as_of date NOT NULL,
  scenario text NOT NULL,
  horizon_days integer NOT NULL,
  input_revision text NOT NULL,
  status text NOT NULL,
  quality_flags jsonb NOT NULL DEFAULT '[]',
  opening_amount numeric(20, 2),
  gap_date date,
  gap_amount numeric(20, 2),
  created_at timestamptz NOT NULL,
  CONSTRAINT forecast_runs_tenant_id_uq UNIQUE (tenant_id, id),
  CONSTRAINT forecast_runs_company_fk
    FOREIGN KEY (tenant_id, company_id) REFERENCES companies (tenant_id, id),
  CONSTRAINT forecast_runs_scenario_ck
    CHECK (scenario IN ('base', 'conservative', 'optimistic')),
  CONSTRAINT forecast_runs_status_ck CHECK (status IN ('ready', 'preliminary', 'stale')),
  CONSTRAINT forecast_runs_horizon_ck CHECK (horizon_days = 91)
);

CREATE INDEX forecast_runs_lookup
  ON forecast_runs (tenant_id, company_id, scenario, as_of, created_at);

CREATE TABLE forecast_points (
  id uuid PRIMARY KEY,
  tenant_id uuid NOT NULL,
  run_id uuid NOT NULL,
  point_date date NOT NULL,
  opening_amount numeric(20, 2) NOT NULL,
  inflows numeric(20, 2) NOT NULL,
  outflows numeric(20, 2) NOT NULL,
  closing_amount numeric(20, 2) NOT NULL,
  CONSTRAINT forecast_points_run_fk
    FOREIGN KEY (tenant_id, run_id) REFERENCES forecast_runs (tenant_id, id),
  CONSTRAINT forecast_points_day_uq UNIQUE (tenant_id, run_id, point_date)
);

CREATE TABLE forecast_contributions (
  id uuid PRIMARY KEY,
  tenant_id uuid NOT NULL,
  run_id uuid NOT NULL,
  point_date date NOT NULL,
  source_type text NOT NULL,
  source_id uuid NOT NULL,
  amount numeric(20, 2) NOT NULL,
  direction text NOT NULL,
  assumption text NOT NULL,
  CONSTRAINT forecast_contributions_run_fk
    FOREIGN KEY (tenant_id, run_id) REFERENCES forecast_runs (tenant_id, id),
  CONSTRAINT forecast_contributions_type_ck CHECK (source_type = 'planned_event'),
  CONSTRAINT forecast_contributions_direction_ck CHECK (direction IN ('in', 'out')),
  CONSTRAINT forecast_contributions_amount_ck CHECK (amount >= 0)
);

ALTER TABLE source_connections DROP CONSTRAINT source_connections_dataset_ck;
ALTER TABLE source_connections ADD CONSTRAINT source_connections_dataset_ck
  CHECK (dataset IN ('cash', 'revenue', 'plan'));

ALTER TABLE source_identities DROP CONSTRAINT source_identities_target_ck;
ALTER TABLE source_identities ADD COLUMN planned_event_id uuid;
ALTER TABLE source_identities ADD CONSTRAINT source_identities_plan_fk
  FOREIGN KEY (tenant_id, planned_event_id)
  REFERENCES planned_cash_events (tenant_id, id);
ALTER TABLE source_identities ADD CONSTRAINT source_identities_target_ck CHECK (
  (
    entity_type = 'cash_transaction'
    AND canonical_entity_id IS NOT NULL
    AND revenue_entry_id IS NULL
    AND planned_event_id IS NULL
  )
  OR (
    entity_type = 'revenue_entry'
    AND revenue_entry_id IS NOT NULL
    AND canonical_entity_id IS NULL
    AND planned_event_id IS NULL
  )
  OR (
    entity_type = 'planned_event'
    AND planned_event_id IS NOT NULL
    AND canonical_entity_id IS NULL
    AND revenue_entry_id IS NULL
  )
);

ALTER TABLE recurrence_rules ENABLE ROW LEVEL SECURITY;
ALTER TABLE recurrence_rules FORCE ROW LEVEL SECURITY;
ALTER TABLE planned_cash_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE planned_cash_events FORCE ROW LEVEL SECURITY;
ALTER TABLE payment_matches ENABLE ROW LEVEL SECURITY;
ALTER TABLE payment_matches FORCE ROW LEVEL SECURITY;
ALTER TABLE obligations ENABLE ROW LEVEL SECURITY;
ALTER TABLE obligations FORCE ROW LEVEL SECURITY;
ALTER TABLE obligation_cash_links ENABLE ROW LEVEL SECURITY;
ALTER TABLE obligation_cash_links FORCE ROW LEVEL SECURITY;
ALTER TABLE forecast_runs ENABLE ROW LEVEL SECURITY;
ALTER TABLE forecast_runs FORCE ROW LEVEL SECURITY;
ALTER TABLE forecast_points ENABLE ROW LEVEL SECURITY;
ALTER TABLE forecast_points FORCE ROW LEVEL SECURITY;
ALTER TABLE forecast_contributions ENABLE ROW LEVEL SECURITY;
ALTER TABLE forecast_contributions FORCE ROW LEVEL SECURITY;

CREATE POLICY recurrence_rules_tenant ON recurrence_rules
  FOR ALL USING (tenant_id = app_tenant()) WITH CHECK (tenant_id = app_tenant());
CREATE POLICY planned_cash_events_tenant ON planned_cash_events
  FOR ALL USING (tenant_id = app_tenant()) WITH CHECK (tenant_id = app_tenant());
CREATE POLICY payment_matches_tenant ON payment_matches
  FOR ALL USING (tenant_id = app_tenant()) WITH CHECK (tenant_id = app_tenant());
CREATE POLICY obligations_tenant ON obligations
  FOR ALL USING (tenant_id = app_tenant()) WITH CHECK (tenant_id = app_tenant());
CREATE POLICY obligation_cash_links_tenant ON obligation_cash_links
  FOR ALL USING (tenant_id = app_tenant()) WITH CHECK (tenant_id = app_tenant());
CREATE POLICY forecast_runs_tenant ON forecast_runs
  FOR ALL USING (tenant_id = app_tenant()) WITH CHECK (tenant_id = app_tenant());
CREATE POLICY forecast_points_tenant ON forecast_points
  FOR ALL USING (tenant_id = app_tenant()) WITH CHECK (tenant_id = app_tenant());
CREATE POLICY forecast_contributions_tenant ON forecast_contributions
  FOR ALL USING (tenant_id = app_tenant()) WITH CHECK (tenant_id = app_tenant());

GRANT SELECT, INSERT, UPDATE ON
  recurrence_rules, planned_cash_events, payment_matches, obligations,
  obligation_cash_links, forecast_runs, forecast_points, forecast_contributions
TO finpilot_app, finpilot_worker;
