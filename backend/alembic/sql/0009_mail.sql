ALTER TABLE source_connections DROP CONSTRAINT source_connections_type_ck;
ALTER TABLE source_connections ADD CONSTRAINT source_connections_type_ck
  CHECK (type IN ('file', 'clientbank', 'onec', 'email'));

ALTER TABLE source_connections ADD COLUMN poll_interval_minutes integer NOT NULL DEFAULT 30;
ALTER TABLE source_connections ADD COLUMN last_attempt_at timestamptz;
ALTER TABLE source_connections ADD COLUMN last_success_at timestamptz;
ALTER TABLE source_connections ADD COLUMN next_attempt_at timestamptz;
ALTER TABLE source_connections ADD COLUMN config_redacted jsonb NOT NULL DEFAULT '{}'::jsonb;
ALTER TABLE source_connections ADD COLUMN encrypted_credentials text;
ALTER TABLE source_connections ADD COLUMN last_error text;
ALTER TABLE source_connections ADD CONSTRAINT source_connections_poll_ck
  CHECK (poll_interval_minutes BETWEEN 5 AND 1440);

CREATE TABLE email_ingestions (
  id uuid PRIMARY KEY,
  tenant_id uuid NOT NULL,
  connection_id uuid NOT NULL,
  batch_id uuid,
  uidvalidity bigint NOT NULL,
  uid bigint NOT NULL,
  message_id text,
  attachment_hash text NOT NULL,
  status text NOT NULL,
  created_at timestamptz NOT NULL,
  CONSTRAINT email_ingestions_tenant_id_uq UNIQUE (tenant_id, id),
  CONSTRAINT email_ingestions_connection_fk
    FOREIGN KEY (tenant_id, connection_id) REFERENCES source_connections (tenant_id, id),
  CONSTRAINT email_ingestions_batch_fk
    FOREIGN KEY (tenant_id, batch_id) REFERENCES import_batches (tenant_id, id),
  CONSTRAINT email_ingestions_status_ck
    CHECK (status IN ('ignored', 'preview', 'failed', 'committed')),
  CONSTRAINT email_ingestions_key_uq
    UNIQUE (tenant_id, connection_id, uidvalidity, uid, attachment_hash)
);

CREATE OR REPLACE FUNCTION app_list_email_sources(p_at timestamptz)
RETURNS TABLE(source_id uuid, source_tenant_id uuid, source_company_id uuid)
LANGUAGE sql SECURITY DEFINER SET search_path = public AS $$
  SELECT id, tenant_id, company_id
  FROM source_connections
  WHERE type = 'email'
    AND enabled
    AND status = 'active'
    AND (next_attempt_at IS NULL OR next_attempt_at <= p_at)
$$;

REVOKE ALL ON FUNCTION app_list_email_sources(timestamptz) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION app_list_email_sources(timestamptz)
  TO finpilot_app, finpilot_worker;

ALTER TABLE email_ingestions ENABLE ROW LEVEL SECURITY;
ALTER TABLE email_ingestions FORCE ROW LEVEL SECURITY;
CREATE POLICY email_ingestions_tenant ON email_ingestions
  FOR ALL USING (tenant_id = app_tenant()) WITH CHECK (tenant_id = app_tenant());

GRANT SELECT, INSERT, UPDATE ON email_ingestions TO finpilot_app, finpilot_worker;
