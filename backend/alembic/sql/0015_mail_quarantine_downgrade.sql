DO $$
BEGIN
  IF EXISTS (
    SELECT 1
    FROM mail_quarantine_entries
    WHERE status = 'open' AND admission_outcome = 'review'
  ) THEN
    RAISE EXCEPTION 'downgrade_blocked: open mail quarantine review entries';
  END IF;
END
$$;

DROP POLICY IF EXISTS mail_quarantine_entries_worker_update ON mail_quarantine_entries;
DROP POLICY IF EXISTS mail_quarantine_entries_worker_select ON mail_quarantine_entries;
DROP POLICY IF EXISTS mail_quarantine_entries_app_update ON mail_quarantine_entries;
DROP POLICY IF EXISTS mail_quarantine_entries_app_insert ON mail_quarantine_entries;
DROP POLICY IF EXISTS mail_quarantine_entries_app_select ON mail_quarantine_entries;
DROP POLICY IF EXISTS mail_quarantine_entries_update ON mail_quarantine_entries;
DROP POLICY IF EXISTS mail_quarantine_entries_insert ON mail_quarantine_entries;
DROP POLICY IF EXISTS mail_quarantine_entries_select ON mail_quarantine_entries;
DROP POLICY IF EXISTS mail_quarantine_entries_tenant ON mail_quarantine_entries;
DROP POLICY IF EXISTS mail_quarantine_entries_retention ON mail_quarantine_entries;
DROP POLICY IF EXISTS mail_quarantine_daily_stats_worker ON mail_quarantine_daily_stats;
DROP POLICY IF EXISTS mail_quarantine_daily_stats_app ON mail_quarantine_daily_stats;
DROP POLICY IF EXISTS mail_quarantine_daily_stats_tenant ON mail_quarantine_daily_stats;
DROP POLICY IF EXISTS mail_quarantine_miss_metrics_worker ON mail_quarantine_miss_metrics;
DROP POLICY IF EXISTS mail_quarantine_miss_metrics_app ON mail_quarantine_miss_metrics;
DROP POLICY IF EXISTS mail_quarantine_miss_metrics_tenant ON mail_quarantine_miss_metrics;

DROP TRIGGER IF EXISTS mail_quarantine_entries_write_guard_trg ON mail_quarantine_entries;
DROP FUNCTION IF EXISTS mail_quarantine_entries_write_guard();

DROP FUNCTION IF EXISTS app_expire_mail_quarantine_entries(timestamptz, integer);
DROP FUNCTION IF EXISTS app_record_mail_quarantine(
  uuid, uuid, uuid, bigint, bigint, char(64), text, text, text, text, text, jsonb, text, integer, timestamptz, timestamptz
);

DROP TABLE IF EXISTS mail_quarantine_entries;
DROP TABLE IF EXISTS mail_quarantine_daily_stats;
DROP TABLE IF EXISTS mail_quarantine_miss_metrics;

DROP FUNCTION IF EXISTS mail_quarantine_metadata_keys_ok(jsonb);
