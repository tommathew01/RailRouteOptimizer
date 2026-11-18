-- Least-privilege runtime role for a MANAGED PostgreSQL (Render, RDS, Cloud SQL, …).
-- docs/11_PRODUCTION_DEPLOYMENT.md §7 · same grants as initdb/01-create-app-role.sh, which only
-- runs for the Docker image's first start.
--
-- Run once as the database owner — before or after `alembic upgrade head` (existing tables are
-- granted too, and tables the owner creates later are granted automatically):
--
--   psql "$OWNER_EXTERNAL_DATABASE_URL" -v ON_ERROR_STOP=1 \
--        -v app_user=railroute_app -v app_password='<a long random password>' \
--        -f infrastructure/postgres/managed-app-role.sql
--
-- The runtime role can read and write rows but cannot create, alter or drop tables.

SELECT format('CREATE ROLE %I LOGIN PASSWORD %L', :'app_user', :'app_password')
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = :'app_user') \gexec

SELECT format('GRANT CONNECT, TEMPORARY ON DATABASE %I TO %I', current_database(), :'app_user') \gexec
SELECT format('GRANT USAGE ON SCHEMA public TO %I', :'app_user') \gexec
SELECT format('GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO %I', :'app_user') \gexec
SELECT format('GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO %I', :'app_user') \gexec
SELECT format(
  'ALTER DEFAULT PRIVILEGES FOR ROLE %I IN SCHEMA public '
  'GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO %I', current_user, :'app_user') \gexec
SELECT format(
  'ALTER DEFAULT PRIVILEGES FOR ROLE %I IN SCHEMA public '
  'GRANT USAGE, SELECT ON SEQUENCES TO %I', current_user, :'app_user') \gexec
