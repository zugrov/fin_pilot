CREATE TABLE telegram_link_tokens (
  id uuid PRIMARY KEY,
  tenant_id uuid NOT NULL REFERENCES tenants (id),
  user_id uuid NOT NULL REFERENCES users (id),
  token_hash text NOT NULL UNIQUE,
  expires_at timestamptz NOT NULL,
  used_at timestamptz,
  created_at timestamptz NOT NULL,
  CONSTRAINT telegram_link_tokens_tenant_id_uq UNIQUE (tenant_id, id)
);

CREATE TABLE telegram_bindings (
  id uuid PRIMARY KEY,
  tenant_id uuid NOT NULL REFERENCES tenants (id),
  user_id uuid NOT NULL REFERENCES users (id),
  telegram_user_id bigint NOT NULL,
  chat_id bigint NOT NULL,
  status text NOT NULL,
  linked_at timestamptz,
  revoked_at timestamptz,
  created_at timestamptz NOT NULL,
  CONSTRAINT telegram_bindings_tenant_id_uq UNIQUE (tenant_id, id),
  CONSTRAINT telegram_bindings_status_ck CHECK (status IN ('pending', 'active', 'revoked')),
  CONSTRAINT telegram_bindings_linked_ck CHECK (
    (status = 'active' AND linked_at IS NOT NULL AND revoked_at IS NULL)
    OR (status = 'pending' AND linked_at IS NULL AND revoked_at IS NULL)
    OR (status = 'revoked' AND revoked_at IS NOT NULL)
  )
);

CREATE UNIQUE INDEX uq_telegram_binding_active
  ON telegram_bindings (tenant_id, user_id)
  WHERE status = 'active';

CREATE UNIQUE INDEX uq_telegram_binding_pending
  ON telegram_bindings (tenant_id, user_id)
  WHERE status = 'pending';

CREATE TABLE digest_subscriptions (
  id uuid PRIMARY KEY,
  tenant_id uuid NOT NULL,
  user_id uuid NOT NULL REFERENCES users (id),
  binding_id uuid NOT NULL,
  company_scope jsonb,
  local_time time NOT NULL,
  timezone text NOT NULL,
  days_of_week jsonb NOT NULL,
  mode text NOT NULL,
  enabled boolean NOT NULL,
  instant_alerts boolean NOT NULL,
  quiet_start time,
  quiet_end time,
  privacy_level text NOT NULL,
  last_scheduled_for date,
  created_at timestamptz NOT NULL,
  updated_at timestamptz NOT NULL,
  CONSTRAINT digest_subscriptions_tenant_id_uq UNIQUE (tenant_id, id),
  CONSTRAINT digest_subscriptions_binding_fk
    FOREIGN KEY (tenant_id, binding_id) REFERENCES telegram_bindings (tenant_id, id),
  CONSTRAINT digest_subscriptions_mode_ck CHECK (mode IN ('group', 'per_company', 'both')),
  CONSTRAINT digest_subscriptions_privacy_ck CHECK (privacy_level IN ('compact', 'full')),
  CONSTRAINT digest_subscriptions_timezone_ck CHECK (length(btrim(timezone)) > 0)
);

CREATE UNIQUE INDEX uq_digest_subscription_binding
  ON digest_subscriptions (tenant_id, binding_id);

CREATE TABLE digest_snapshots (
  id uuid PRIMARY KEY,
  tenant_id uuid NOT NULL,
  subscription_id uuid NOT NULL,
  kind text NOT NULL,
  request_id text,
  local_date date NOT NULL,
  report_date date NOT NULL,
  scheduled_for timestamptz NOT NULL,
  as_of timestamptz NOT NULL,
  company_ids jsonb NOT NULL,
  metrics_json jsonb NOT NULL,
  quality_json jsonb NOT NULL,
  content_hash text NOT NULL,
  status text NOT NULL,
  created_at timestamptz NOT NULL,
  CONSTRAINT digest_snapshots_tenant_id_uq UNIQUE (tenant_id, id),
  CONSTRAINT digest_snapshots_subscription_fk
    FOREIGN KEY (tenant_id, subscription_id)
    REFERENCES digest_subscriptions (tenant_id, id),
  CONSTRAINT digest_snapshots_kind_ck CHECK (
    (kind = 'scheduled' AND request_id IS NULL)
    OR (kind = 'manual' AND request_id IS NOT NULL)
  ),
  CONSTRAINT digest_snapshots_status_ck CHECK (status = 'ready')
);

CREATE UNIQUE INDEX uq_digest_scheduled
  ON digest_snapshots (subscription_id, local_date)
  WHERE kind = 'scheduled';

CREATE UNIQUE INDEX uq_digest_manual
  ON digest_snapshots (subscription_id, request_id)
  WHERE request_id IS NOT NULL;

CREATE TABLE notification_outbox (
  id uuid PRIMARY KEY,
  tenant_id uuid NOT NULL,
  snapshot_id uuid,
  alert_id uuid,
  binding_id uuid NOT NULL,
  part_number integer NOT NULL,
  materiality text NOT NULL DEFAULT '',
  payload jsonb NOT NULL,
  status text NOT NULL,
  attempts integer NOT NULL DEFAULT 0,
  next_attempt_at timestamptz NOT NULL,
  telegram_message_id bigint,
  last_error text,
  lease_until timestamptz,
  created_at timestamptz NOT NULL,
  sent_at timestamptz,
  CONSTRAINT notification_outbox_tenant_id_uq UNIQUE (tenant_id, id),
  CONSTRAINT notification_outbox_snapshot_fk
    FOREIGN KEY (tenant_id, snapshot_id) REFERENCES digest_snapshots (tenant_id, id),
  CONSTRAINT notification_outbox_alert_fk
    FOREIGN KEY (tenant_id, alert_id) REFERENCES alerts (tenant_id, id),
  CONSTRAINT notification_outbox_binding_fk
    FOREIGN KEY (tenant_id, binding_id) REFERENCES telegram_bindings (tenant_id, id),
  CONSTRAINT notification_outbox_target_ck CHECK (
    (snapshot_id IS NOT NULL AND alert_id IS NULL)
    OR (snapshot_id IS NULL AND alert_id IS NOT NULL)
  ),
  CONSTRAINT notification_outbox_part_ck CHECK (part_number >= 1),
  CONSTRAINT notification_outbox_attempts_ck CHECK (attempts >= 0),
  CONSTRAINT notification_outbox_status_ck CHECK (
    status IN ('pending', 'sending', 'sent', 'retry', 'failed', 'unknown', 'cancelled')
  )
);

CREATE UNIQUE INDEX uq_notification_outbox_part
  ON notification_outbox (snapshot_id, binding_id, part_number)
  WHERE snapshot_id IS NOT NULL;

CREATE UNIQUE INDEX uq_notification_outbox_alert
  ON notification_outbox (alert_id, binding_id, materiality)
  WHERE alert_id IS NOT NULL;

CREATE INDEX notification_outbox_due
  ON notification_outbox (status, next_attempt_at);

CREATE TABLE telegram_updates (
  id uuid PRIMARY KEY,
  bot_id text NOT NULL,
  update_id bigint NOT NULL,
  payload_hash text NOT NULL,
  payload jsonb NOT NULL,
  received_at timestamptz NOT NULL,
  status text NOT NULL,
  tenant_id uuid,
  CONSTRAINT telegram_updates_dedup UNIQUE (bot_id, update_id),
  CONSTRAINT telegram_updates_status_ck CHECK (status IN ('received', 'processed', 'ignored'))
);

CREATE TABLE bot_drafts (
  id uuid PRIMARY KEY,
  tenant_id uuid NOT NULL,
  binding_id uuid NOT NULL,
  state text NOT NULL,
  payload jsonb NOT NULL,
  expires_at timestamptz NOT NULL,
  idempotency_key text,
  created_at timestamptz NOT NULL,
  updated_at timestamptz NOT NULL,
  CONSTRAINT bot_drafts_tenant_id_uq UNIQUE (tenant_id, id),
  CONSTRAINT bot_drafts_binding_fk
    FOREIGN KEY (tenant_id, binding_id) REFERENCES telegram_bindings (tenant_id, id),
  CONSTRAINT bot_drafts_state_ck CHECK (
    state IN (
      'company', 'direction', 'wallet', 'amount', 'date', 'category',
      'flow', 'comment', 'preview', 'done', 'cancelled'
    )
  )
);

CREATE UNIQUE INDEX uq_bot_draft_open
  ON bot_drafts (binding_id)
  WHERE state NOT IN ('done', 'cancelled');

CREATE UNIQUE INDEX uq_bot_draft_idempotency
  ON bot_drafts (idempotency_key)
  WHERE idempotency_key IS NOT NULL;

CREATE OR REPLACE FUNCTION app_consume_link_token(p_hash text, p_at timestamptz)
RETURNS TABLE(token_user_id uuid, token_tenant_id uuid)
LANGUAGE sql SECURITY DEFINER SET search_path = public AS $$
  UPDATE telegram_link_tokens AS token
  SET used_at = p_at
  WHERE token.token_hash = p_hash
    AND token.used_at IS NULL
    AND token.expires_at > p_at
  RETURNING token.user_id, token.tenant_id
$$;

CREATE OR REPLACE FUNCTION app_binding_by_telegram(p_telegram_user_id bigint)
RETURNS TABLE(
  binding_id uuid,
  binding_tenant_id uuid,
  binding_user_id uuid,
  binding_chat_id bigint,
  binding_status text
)
LANGUAGE sql SECURITY DEFINER SET search_path = public AS $$
  SELECT id, tenant_id, user_id, chat_id, status
  FROM telegram_bindings
  WHERE telegram_user_id = p_telegram_user_id
    AND status IN ('pending', 'active')
  ORDER BY CASE status WHEN 'active' THEN 0 ELSE 1 END
  LIMIT 1
$$;

CREATE OR REPLACE FUNCTION app_record_telegram_update(
  p_id uuid,
  p_bot_id text,
  p_update_id bigint,
  p_payload_hash text,
  p_payload jsonb,
  p_at timestamptz
) RETURNS boolean
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
BEGIN
  INSERT INTO telegram_updates (
    id, bot_id, update_id, payload_hash, payload, received_at, status
  ) VALUES (
    p_id, p_bot_id, p_update_id, p_payload_hash, p_payload, p_at, 'received'
  )
  ON CONFLICT (bot_id, update_id) DO NOTHING;
  RETURN FOUND;
END;
$$;

CREATE OR REPLACE FUNCTION app_finish_telegram_update(
  p_id uuid,
  p_status text,
  p_tenant uuid
) RETURNS void
LANGUAGE sql SECURITY DEFINER SET search_path = public AS $$
  UPDATE telegram_updates
  SET status = p_status, tenant_id = p_tenant
  WHERE id = p_id
$$;

CREATE OR REPLACE FUNCTION app_list_digest_subscriptions()
RETURNS TABLE(
  subscription_id uuid,
  subscription_tenant_id uuid,
  subscription_user_id uuid,
  subscription_binding_id uuid
)
LANGUAGE sql SECURITY DEFINER SET search_path = public AS $$
  SELECT subscription.id, subscription.tenant_id, subscription.user_id, subscription.binding_id
  FROM digest_subscriptions AS subscription
  JOIN telegram_bindings AS binding ON binding.id = subscription.binding_id
  WHERE subscription.enabled AND binding.status = 'active'
$$;

CREATE OR REPLACE FUNCTION app_expire_notification_leases(p_at timestamptz)
RETURNS integer
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE
  changed integer;
BEGIN
  UPDATE notification_outbox
  SET status = 'unknown', last_error = 'lease'
  WHERE status = 'sending' AND lease_until IS NOT NULL AND lease_until < p_at;
  GET DIAGNOSTICS changed = ROW_COUNT;
  RETURN changed;
END;
$$;

CREATE OR REPLACE FUNCTION app_claim_notification_outbox(p_at timestamptz, p_limit integer)
RETURNS SETOF notification_outbox
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
BEGIN
  RETURN QUERY
  UPDATE notification_outbox AS item
  SET status = 'sending', lease_until = p_at + interval '60 seconds'
  WHERE item.id IN (
    SELECT queued.id
    FROM notification_outbox AS queued
    WHERE queued.status IN ('pending', 'retry')
      AND queued.next_attempt_at <= p_at
      AND (queued.lease_until IS NULL OR queued.lease_until < p_at)
    ORDER BY queued.next_attempt_at, queued.part_number
    LIMIT p_limit
    FOR UPDATE SKIP LOCKED
  )
  RETURNING item.*;
END;
$$;

REVOKE ALL ON FUNCTION app_consume_link_token(text, timestamptz) FROM PUBLIC;
REVOKE ALL ON FUNCTION app_binding_by_telegram(bigint) FROM PUBLIC;
REVOKE ALL ON FUNCTION app_record_telegram_update(uuid, text, bigint, text, jsonb, timestamptz)
  FROM PUBLIC;
REVOKE ALL ON FUNCTION app_finish_telegram_update(uuid, text, uuid) FROM PUBLIC;
REVOKE ALL ON FUNCTION app_list_digest_subscriptions() FROM PUBLIC;
REVOKE ALL ON FUNCTION app_expire_notification_leases(timestamptz) FROM PUBLIC;
REVOKE ALL ON FUNCTION app_claim_notification_outbox(timestamptz, integer) FROM PUBLIC;

GRANT EXECUTE ON FUNCTION app_consume_link_token(text, timestamptz)
  TO finpilot_app, finpilot_worker;
GRANT EXECUTE ON FUNCTION app_binding_by_telegram(bigint)
  TO finpilot_app, finpilot_worker;
GRANT EXECUTE ON FUNCTION app_record_telegram_update(uuid, text, bigint, text, jsonb, timestamptz)
  TO finpilot_app, finpilot_worker;
GRANT EXECUTE ON FUNCTION app_finish_telegram_update(uuid, text, uuid)
  TO finpilot_app, finpilot_worker;
GRANT EXECUTE ON FUNCTION app_list_digest_subscriptions()
  TO finpilot_app, finpilot_worker;
GRANT EXECUTE ON FUNCTION app_expire_notification_leases(timestamptz)
  TO finpilot_app, finpilot_worker;
GRANT EXECUTE ON FUNCTION app_claim_notification_outbox(timestamptz, integer)
  TO finpilot_app, finpilot_worker;

ALTER TABLE telegram_link_tokens ENABLE ROW LEVEL SECURITY;
ALTER TABLE telegram_link_tokens FORCE ROW LEVEL SECURITY;
ALTER TABLE telegram_bindings ENABLE ROW LEVEL SECURITY;
ALTER TABLE telegram_bindings FORCE ROW LEVEL SECURITY;
ALTER TABLE digest_subscriptions ENABLE ROW LEVEL SECURITY;
ALTER TABLE digest_subscriptions FORCE ROW LEVEL SECURITY;
ALTER TABLE digest_snapshots ENABLE ROW LEVEL SECURITY;
ALTER TABLE digest_snapshots FORCE ROW LEVEL SECURITY;
ALTER TABLE notification_outbox ENABLE ROW LEVEL SECURITY;
ALTER TABLE notification_outbox FORCE ROW LEVEL SECURITY;
ALTER TABLE telegram_updates ENABLE ROW LEVEL SECURITY;
ALTER TABLE telegram_updates FORCE ROW LEVEL SECURITY;
ALTER TABLE bot_drafts ENABLE ROW LEVEL SECURITY;
ALTER TABLE bot_drafts FORCE ROW LEVEL SECURITY;

CREATE POLICY telegram_link_tokens_tenant ON telegram_link_tokens
  FOR ALL USING (tenant_id = app_tenant()) WITH CHECK (tenant_id = app_tenant());
CREATE POLICY telegram_bindings_tenant ON telegram_bindings
  FOR ALL USING (tenant_id = app_tenant()) WITH CHECK (tenant_id = app_tenant());
CREATE POLICY digest_subscriptions_tenant ON digest_subscriptions
  FOR ALL USING (tenant_id = app_tenant()) WITH CHECK (tenant_id = app_tenant());
CREATE POLICY digest_snapshots_tenant ON digest_snapshots
  FOR ALL USING (tenant_id = app_tenant()) WITH CHECK (tenant_id = app_tenant());
CREATE POLICY notification_outbox_tenant ON notification_outbox
  FOR ALL USING (tenant_id = app_tenant()) WITH CHECK (tenant_id = app_tenant());
CREATE POLICY telegram_updates_tenant ON telegram_updates
  FOR ALL USING (tenant_id = app_tenant()) WITH CHECK (tenant_id = app_tenant());
CREATE POLICY bot_drafts_tenant ON bot_drafts
  FOR ALL USING (tenant_id = app_tenant()) WITH CHECK (tenant_id = app_tenant());

GRANT SELECT, INSERT, UPDATE ON
  telegram_link_tokens, telegram_bindings, digest_subscriptions, digest_snapshots,
  notification_outbox, telegram_updates, bot_drafts
TO finpilot_app, finpilot_worker;
