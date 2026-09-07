#!/bin/bash
set -e

# Start service
service postgresql start

# Allow local access without password hassles
echo "local   all             all                                     trust" > /etc/postgresql/16/main/pg_hba.conf
echo "host    all             all             127.0.0.1/32            trust" >> /etc/postgresql/16/main/pg_hba.conf
echo "host    all             all             ::1/128                 trust" >> /etc/postgresql/16/main/pg_hba.conf
echo "host    all             all             all                     trust" >> /etc/postgresql/16/main/pg_hba.conf
echo "listen_addresses = '*'" >> /etc/postgresql/16/main/postgresql.conf

# Restart to pick up config
service postgresql restart

# Run init SQL
su - postgres -c "psql -c \"ALTER USER postgres WITH PASSWORD 'postgres';\""
su - postgres -c "psql -c \"DROP DATABASE IF EXISTS dietsync;\""
su - postgres -c "psql -c \"CREATE DATABASE dietsync;\""
su - postgres -c "psql -d dietsync -c \"CREATE EXTENSION IF NOT EXISTS pg_trgm;\""
su - postgres -c "psql -d dietsync -c \"CREATE EXTENSION IF NOT EXISTS pgcrypto;\""
su - postgres -c "psql -d dietsync -c \"CREATE EXTENSION IF NOT EXISTS \\\"uuid-ossp\\\";\""

echo "Postgres setup completed successfully!"
