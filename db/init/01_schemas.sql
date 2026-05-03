-- Schema layout mirrors a Snowflake/Databricks medallion architecture so the
-- same dbt models can lift-and-shift to a cloud warehouse unchanged.

CREATE SCHEMA IF NOT EXISTS raw;            -- bronze: untouched landings from source systems
CREATE SCHEMA IF NOT EXISTS staging;        -- silver: dbt staging models (cleaned, conformed)
CREATE SCHEMA IF NOT EXISTS intermediate;   -- silver: dbt intermediate models (joined, enriched)
CREATE SCHEMA IF NOT EXISTS marts;          -- gold: dbt marts (recon results consumed by Streamlit)
CREATE SCHEMA IF NOT EXISTS audit;          -- SOX-style immutable run log

COMMENT ON SCHEMA raw IS 'Bronze layer. Untouched landings from source systems (AP, AR, Inventory, GL).';
COMMENT ON SCHEMA staging IS 'Silver layer. dbt staging models. One stg_ model per source table.';
COMMENT ON SCHEMA intermediate IS 'Silver layer. dbt intermediate models. Joins and enrichment.';
COMMENT ON SCHEMA marts IS 'Gold layer. dbt marts. Recon checks and analytics-ready tables.';
COMMENT ON SCHEMA audit IS 'SOX-style audit trail. Append-only run log for control evidence.';
