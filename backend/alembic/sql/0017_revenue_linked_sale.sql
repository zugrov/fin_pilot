-- P3-0: опциональная связь return → sale (expand-only).

SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '60s';

ALTER TABLE revenue_entries
  ADD COLUMN linked_sale_entry_id uuid NULL;

ALTER TABLE revenue_entries
  ADD CONSTRAINT revenue_entries_linked_sale_fk
  FOREIGN KEY (linked_sale_entry_id)
  REFERENCES revenue_entries (id)
  ON DELETE NO ACTION
  NOT VALID;

ALTER TABLE revenue_entries
  VALIDATE CONSTRAINT revenue_entries_linked_sale_fk;

CREATE INDEX revenue_entries_linked_sale_idx
  ON revenue_entries (linked_sale_entry_id)
  WHERE linked_sale_entry_id IS NOT NULL;
