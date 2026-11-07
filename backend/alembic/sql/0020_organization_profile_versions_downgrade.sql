SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '60s';

DROP TRIGGER IF EXISTS organization_profile_versions_guard_tr ON organization_profile_versions;
DROP FUNCTION IF EXISTS organization_profile_versions_guard();
DROP TABLE IF EXISTS organization_profile_versions;
