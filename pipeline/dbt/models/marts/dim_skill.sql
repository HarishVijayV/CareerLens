-- Postgres syntax (unnest) — this is the one model you'd rewrite for Snowflake, which
-- uses FLATTEN(input => column) instead of UNNEST. Worth knowing that dialect
-- differences are exactly this localized: one model, not a rewrite of the whole project.
select distinct
    md5(skill) as skill_id,
    skill
from {{ ref('stg_postings') }}, unnest(required_skills) as skill
where skill is not null
