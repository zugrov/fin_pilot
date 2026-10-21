CREATE TABLE mail_quarantine_daily_stats (
  tenant_id uuid NOT NULL,
  company_id uuid NOT NULL,
  connection_id uuid NOT NULL,
  day_utc date NOT NULL,
  entries_created integer NOT NULL DEFAULT 0,
  overflow_count integer NOT NULL DEFAULT 0,
  PRIMARY KEY (tenant_id, company_id, connection_id, day_utc),
  CONSTRAINT mail_quarantine_daily_stats_company_fk
    FOREIGN KEY (tenant_id, company_id) REFERENCES companies (tenant_id, id),
  CONSTRAINT mail_quarantine_daily_stats_connection_fk
    FOREIGN KEY (tenant_id, company_id, connection_id)
    REFERENCES source_connections (tenant_id, company_id, id)
);

CREATE TABLE mail_quarantine_miss_metrics (
  tenant_id uuid NOT NULL,
  company_id uuid NOT NULL,
  connection_id uuid NOT NULL,
  reason text NOT NULL,
  hit_count bigint NOT NULL DEFAULT 0,
  last_at timestamptz NOT NULL,
  PRIMARY KEY (tenant_id, company_id, connection_id, reason)
);

CREATE TABLE mail_quarantine_entries (
  id uuid PRIMARY KEY,
  tenant_id uuid NOT NULL,
  company_id uuid NOT NULL,
  connection_id uuid NOT NULL,
  channel text NOT NULL DEFAULT 'email',
  uidvalidity bigint NOT NULL,
  uid bigint NOT NULL,
  message_digest char(64) NOT NULL,
  message_id_header text,
  ingress_stage text NOT NULL,
  reason_code text NOT NULL,
  admission_outcome text NOT NULL,
  sender_normalized text,
  metadata_allowed jsonb NOT NULL DEFAULT '{}'::jsonb,
  slot_content_anomaly boolean NOT NULL DEFAULT false,
  transport_trust_level text NOT NULL DEFAULT 'fixture',
  status text NOT NULL DEFAULT 'open',
  reviewer_user_id uuid,
  resolution text,
  resolution_note text,
  created_at timestamptz NOT NULL,
  resolved_at timestamptz,
  retain_until timestamptz NOT NULL,
  CONSTRAINT mail_quarantine_entries_tenant_id_uq UNIQUE (tenant_id, id),
  CONSTRAINT mail_quarantine_entries_slot_digest_uq
    UNIQUE (tenant_id, company_id, connection_id, uidvalidity, uid, message_digest),
  CONSTRAINT mail_quarantine_entries_channel_ck CHECK (channel = 'email'),
  CONSTRAINT mail_quarantine_entries_stage_ck
    CHECK (ingress_stage IN ('rejected', 'review')),
  CONSTRAINT mail_quarantine_entries_outcome_ck
    CHECK (admission_outcome IN ('reject', 'review')),
  CONSTRAINT mail_quarantine_entries_status_ck
    CHECK (status IN ('open', 'closed', 'expired')),
  CONSTRAINT mail_quarantine_entries_resolution_ck
    CHECK (resolution IS NULL OR resolution IN ('dismissed', 'escalated')),
  CONSTRAINT mail_quarantine_entries_sender_scope_ck
    CHECK (admission_outcome <> 'reject' OR sender_normalized IS NULL),
  CONSTRAINT mail_quarantine_entries_company_fk
    FOREIGN KEY (tenant_id, company_id) REFERENCES companies (tenant_id, id),
  CONSTRAINT mail_quarantine_entries_connection_fk
    FOREIGN KEY (tenant_id, company_id, connection_id)
    REFERENCES source_connections (tenant_id, company_id, id)
);

CREATE INDEX mail_quarantine_entries_open_idx
  ON mail_quarantine_entries (tenant_id, company_id, status, created_at DESC);

CREATE INDEX mail_quarantine_entries_slot_idx
  ON mail_quarantine_entries (tenant_id, connection_id, uidvalidity, uid);

CREATE INDEX mail_quarantine_entries_retain_idx
  ON mail_quarantine_entries (retain_until)
  WHERE status IN ('open', 'closed');

CREATE OR REPLACE FUNCTION mail_quarantine_metadata_keys_ok(p jsonb)
RETURNS boolean
LANGUAGE sql
IMMUTABLE
AS $$
  SELECT COALESCE(
    (
      SELECT bool_and(
        k = ANY (
          ARRAY[
            'reason_code',
            'stage',
            'sender_domain',
            'attachment_count',
            'attachment_total_bytes',
            'content_types',
            'extensions'
          ]::text[]
        )
      )
      FROM jsonb_object_keys(p) AS k
    ),
    true
  )
$$;

ALTER TABLE mail_quarantine_entries
  ADD CONSTRAINT mail_quarantine_entries_metadata_keys_ck
  CHECK (mail_quarantine_metadata_keys_ok(metadata_allowed));

ALTER TABLE mail_quarantine_entries ENABLE ROW LEVEL SECURITY;
ALTER TABLE mail_quarantine_entries FORCE ROW LEVEL SECURITY;

CREATE POLICY mail_quarantine_entries_app_select ON mail_quarantine_entries
  AS PERMISSIVE
  FOR SELECT
  TO finpilot_app
  USING (tenant_id = app_tenant());

CREATE POLICY mail_quarantine_entries_app_insert ON mail_quarantine_entries
  AS PERMISSIVE
  FOR INSERT
  TO finpilot_app
  WITH CHECK (tenant_id = app_tenant());

CREATE POLICY mail_quarantine_entries_app_update ON mail_quarantine_entries
  AS PERMISSIVE
  FOR UPDATE
  TO finpilot_app
  USING (tenant_id = app_tenant())
  WITH CHECK (tenant_id = app_tenant());

CREATE POLICY mail_quarantine_entries_worker_select ON mail_quarantine_entries
  AS PERMISSIVE
  FOR SELECT
  TO finpilot_worker
  USING (
    tenant_id = app_tenant()
    OR current_setting('app.mail_quarantine_retention', true) = '1'
  );

CREATE POLICY mail_quarantine_entries_worker_update ON mail_quarantine_entries
  AS PERMISSIVE
  FOR UPDATE
  TO finpilot_worker
  USING (
    tenant_id = app_tenant()
    OR current_setting('app.mail_quarantine_retention', true) = '1'
  )
  WITH CHECK (
    tenant_id = app_tenant()
    OR current_setting('app.mail_quarantine_retention', true) = '1'
  );

ALTER TABLE mail_quarantine_daily_stats ENABLE ROW LEVEL SECURITY;
ALTER TABLE mail_quarantine_daily_stats FORCE ROW LEVEL SECURITY;

CREATE POLICY mail_quarantine_daily_stats_app ON mail_quarantine_daily_stats
  AS PERMISSIVE
  FOR ALL
  TO finpilot_app
  USING (tenant_id = app_tenant())
  WITH CHECK (tenant_id = app_tenant());

CREATE POLICY mail_quarantine_daily_stats_worker ON mail_quarantine_daily_stats
  AS PERMISSIVE
  FOR ALL
  TO finpilot_worker
  USING (tenant_id = app_tenant())
  WITH CHECK (tenant_id = app_tenant());

ALTER TABLE mail_quarantine_miss_metrics ENABLE ROW LEVEL SECURITY;
ALTER TABLE mail_quarantine_miss_metrics FORCE ROW LEVEL SECURITY;

CREATE POLICY mail_quarantine_miss_metrics_app ON mail_quarantine_miss_metrics
  AS PERMISSIVE
  FOR ALL
  TO finpilot_app
  USING (tenant_id = app_tenant())
  WITH CHECK (tenant_id = app_tenant());

CREATE POLICY mail_quarantine_miss_metrics_worker ON mail_quarantine_miss_metrics
  AS PERMISSIVE
  FOR ALL
  TO finpilot_worker
  USING (tenant_id = app_tenant())
  WITH CHECK (tenant_id = app_tenant());

CREATE OR REPLACE FUNCTION mail_quarantine_entries_write_guard()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
  IF current_setting('app.mail_quarantine_internal', true) IS DISTINCT FROM '1' THEN
    RAISE EXCEPTION 'mail_quarantine_direct_write_forbidden';
  END IF;
  IF TG_OP = 'UPDATE' THEN
    IF NEW.reason_code IS DISTINCT FROM OLD.reason_code
      OR NEW.ingress_stage IS DISTINCT FROM OLD.ingress_stage
      OR NEW.admission_outcome IS DISTINCT FROM OLD.admission_outcome
      OR NEW.uidvalidity IS DISTINCT FROM OLD.uidvalidity
      OR NEW.uid IS DISTINCT FROM OLD.uid
      OR NEW.message_digest IS DISTINCT FROM OLD.message_digest
      OR NEW.tenant_id IS DISTINCT FROM OLD.tenant_id
      OR NEW.company_id IS DISTINCT FROM OLD.company_id
      OR NEW.connection_id IS DISTINCT FROM OLD.connection_id
    THEN
      RAISE EXCEPTION 'mail_quarantine_immutable_field';
    END IF;
  END IF;
  RETURN NEW;
END;
$$;

CREATE TRIGGER mail_quarantine_entries_write_guard_trg
  BEFORE INSERT OR UPDATE ON mail_quarantine_entries
  FOR EACH ROW
  EXECUTE FUNCTION mail_quarantine_entries_write_guard();

REVOKE DELETE ON mail_quarantine_entries FROM finpilot_app, finpilot_worker;
REVOKE DELETE ON mail_quarantine_daily_stats FROM finpilot_app, finpilot_worker;
REVOKE DELETE ON mail_quarantine_miss_metrics FROM finpilot_app, finpilot_worker;

GRANT SELECT ON mail_quarantine_entries TO finpilot_app, finpilot_worker;
GRANT SELECT ON mail_quarantine_daily_stats TO finpilot_app, finpilot_worker;
GRANT SELECT ON mail_quarantine_miss_metrics TO finpilot_app, finpilot_worker;

GRANT INSERT, UPDATE ON mail_quarantine_entries TO finpilot_app, finpilot_worker;
GRANT INSERT, UPDATE ON mail_quarantine_daily_stats TO finpilot_app;
GRANT INSERT, UPDATE ON mail_quarantine_miss_metrics TO finpilot_app;

CREATE OR REPLACE FUNCTION app_record_mail_quarantine(
  p_tenant_id uuid,
  p_company_id uuid,
  p_connection_id uuid,
  p_uidvalidity bigint,
  p_uid bigint,
  p_message_digest char(64),
  p_message_id_header text,
  p_ingress_stage text,
  p_reason_code text,
  p_admission_outcome text,
  p_sender_normalized text,
  p_metadata_allowed jsonb,
  p_transport_trust_level text,
  p_daily_limit integer,
  p_at timestamptz,
  p_retain_until timestamptz
)
RETURNS uuid
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
  v_source_id uuid;
  v_day date := (timezone('UTC', p_at))::date;
  v_stats mail_quarantine_daily_stats%ROWTYPE;
  v_new_id uuid;
  v_existing uuid;
BEGIN
  PERFORM set_config('app.tenant_id', p_tenant_id::text, true);
  PERFORM set_config('app.mail_quarantine_internal', '1', true);

  SELECT id INTO v_source_id
  FROM source_connections
  WHERE id = p_connection_id
    AND tenant_id = p_tenant_id
    AND company_id = p_company_id
    AND type = 'email';

  IF v_source_id IS NULL THEN
    INSERT INTO mail_quarantine_miss_metrics (
      tenant_id, company_id, connection_id, reason, hit_count, last_at
    )
    VALUES (
      p_tenant_id, p_company_id, p_connection_id, 'source_missing', 1, p_at
    )
    ON CONFLICT (tenant_id, company_id, connection_id, reason)
    DO UPDATE SET
      hit_count = mail_quarantine_miss_metrics.hit_count + 1,
      last_at = EXCLUDED.last_at;
    RETURN NULL;
  END IF;

  IF NOT mail_quarantine_metadata_keys_ok(p_metadata_allowed) THEN
    RAISE EXCEPTION 'mail_quarantine_invalid_metadata';
  END IF;

  INSERT INTO mail_quarantine_daily_stats (
    tenant_id, company_id, connection_id, day_utc, entries_created, overflow_count
  )
  VALUES (p_tenant_id, p_company_id, p_connection_id, v_day, 0, 0)
  ON CONFLICT (tenant_id, company_id, connection_id, day_utc) DO NOTHING;

  SELECT * INTO v_stats
  FROM mail_quarantine_daily_stats
  WHERE tenant_id = p_tenant_id
    AND company_id = p_company_id
    AND connection_id = p_connection_id
    AND day_utc = v_day
  FOR UPDATE;

  SELECT id INTO v_existing
  FROM mail_quarantine_entries
  WHERE tenant_id = p_tenant_id
    AND company_id = p_company_id
    AND connection_id = p_connection_id
    AND uidvalidity = p_uidvalidity
    AND uid = p_uid
    AND message_digest = p_message_digest;

  IF v_existing IS NOT NULL THEN
    RETURN v_existing;
  END IF;

  IF v_stats.entries_created >= p_daily_limit THEN
    UPDATE mail_quarantine_daily_stats
    SET overflow_count = overflow_count + 1
    WHERE tenant_id = p_tenant_id
      AND company_id = p_company_id
      AND connection_id = p_connection_id
      AND day_utc = v_day;
    RETURN NULL;
  END IF;

  v_new_id := gen_random_uuid();
  INSERT INTO mail_quarantine_entries (
    id,
    tenant_id,
    company_id,
    connection_id,
    uidvalidity,
    uid,
    message_digest,
    message_id_header,
    ingress_stage,
    reason_code,
    admission_outcome,
    sender_normalized,
    metadata_allowed,
    transport_trust_level,
    created_at,
    retain_until
  )
  VALUES (
    v_new_id,
    p_tenant_id,
    p_company_id,
    p_connection_id,
    p_uidvalidity,
    p_uid,
    p_message_digest,
    NULLIF(p_message_id_header, ''),
    p_ingress_stage,
    p_reason_code,
    p_admission_outcome,
    NULLIF(p_sender_normalized, ''),
    p_metadata_allowed,
    p_transport_trust_level,
    p_at,
    p_retain_until
  );

  UPDATE mail_quarantine_daily_stats
  SET entries_created = entries_created + 1
  WHERE tenant_id = p_tenant_id
    AND company_id = p_company_id
    AND connection_id = p_connection_id
    AND day_utc = v_day;

  UPDATE mail_quarantine_entries
  SET slot_content_anomaly = true
  WHERE tenant_id = p_tenant_id
    AND company_id = p_company_id
    AND connection_id = p_connection_id
    AND uidvalidity = p_uidvalidity
    AND uid = p_uid;

  RETURN v_new_id;
END;
$$;

CREATE OR REPLACE FUNCTION app_expire_mail_quarantine_entries(
  p_before timestamptz,
  p_limit integer
)
RETURNS integer
LANGUAGE plpgsql
SECURITY INVOKER
SET search_path = public
AS $$
DECLARE
  v_row mail_quarantine_entries%ROWTYPE;
  v_count integer := 0;
BEGIN
  PERFORM set_config('app.mail_quarantine_retention', '1', true);
  FOR v_row IN
    SELECT *
    FROM (
      SELECT *
      FROM mail_quarantine_entries
      WHERE retain_until <= p_before
        AND status IN ('open', 'closed')
      ORDER BY retain_until
      FOR UPDATE SKIP LOCKED
      LIMIT p_limit
    ) AS candidates
  LOOP
    PERFORM set_config('app.tenant_id', v_row.tenant_id::text, true);
    PERFORM set_config('app.mail_quarantine_internal', '1', true);
    UPDATE mail_quarantine_entries
    SET
      status = 'expired',
      metadata_allowed = '{}'::jsonb
    WHERE tenant_id = v_row.tenant_id
      AND id = v_row.id;
    v_count := v_count + 1;
  END LOOP;
  PERFORM set_config('app.mail_quarantine_retention', '', true);
  RETURN v_count;
END;
$$;

ALTER FUNCTION app_record_mail_quarantine(
  uuid, uuid, uuid, bigint, bigint, char(64), text, text, text, text, text, jsonb, text, integer, timestamptz, timestamptz
) OWNER TO finpilot_app;

ALTER FUNCTION app_expire_mail_quarantine_entries(timestamptz, integer) OWNER TO finpilot_worker;

REVOKE ALL ON FUNCTION app_record_mail_quarantine(
  uuid, uuid, uuid, bigint, bigint, char(64), text, text, text, text, text, jsonb, text, integer, timestamptz, timestamptz
) FROM PUBLIC;

REVOKE ALL ON FUNCTION app_expire_mail_quarantine_entries(timestamptz, integer) FROM PUBLIC;

GRANT EXECUTE ON FUNCTION app_record_mail_quarantine(
  uuid, uuid, uuid, bigint, bigint, char(64), text, text, text, text, text, jsonb, text, integer, timestamptz, timestamptz
) TO finpilot_app, finpilot_worker;

GRANT EXECUTE ON FUNCTION app_expire_mail_quarantine_entries(timestamptz, integer)
  TO finpilot_worker;
