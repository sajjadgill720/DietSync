-- Enable required extensions for DietSync
-- pg_trgm: Enables trigram operations for gin_trgm_ops index (fuzzy/prefix brand_name autocomplete)
CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- pgcrypto: Provides gen_random_uuid() and cryptographic utilities
CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- uuid-ossp: Standard UUID generation functions
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
