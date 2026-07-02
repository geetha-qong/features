-- Runs only on first Postgres init (volume empty). Postgres image executes
-- *.sql files under /docker-entrypoint-initdb.d/ as the POSTGRES_USER.
-- The `qong` database is auto-created by POSTGRES_DB; this adds the second
-- DB that the label-studio service expects (POSTGRE_NAME=label_studio).
CREATE DATABASE label_studio OWNER qong;
