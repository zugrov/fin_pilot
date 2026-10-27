DO $$
BEGIN
  IF EXISTS (
    SELECT 1
    FROM revenue_entries
    WHERE linked_sale_entry_id IS NOT NULL
    LIMIT 1
  ) THEN
    RAISE EXCEPTION 'downgrade_blocked: linked_sale_entry_id in use';
  END IF;
END $$;

DROP INDEX IF EXISTS revenue_entries_linked_sale_idx;

ALTER TABLE revenue_entries
  DROP CONSTRAINT IF EXISTS revenue_entries_linked_sale_fk;

ALTER TABLE revenue_entries
  DROP COLUMN IF EXISTS linked_sale_entry_id;
