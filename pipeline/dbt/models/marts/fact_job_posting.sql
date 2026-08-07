-- The fact table: one row per posting, foreign-keying out to the dimensions. This +
-- dim_company + dim_skill + fact_application (added in Phase 6, once application
-- tracking exists) together form the star schema described in docs/DATA_ENGINEERING.md.
select
    p.posting_id,
    c.company_id,
    p.title,
    p.location,
    p.region,
    p.seniority,
    p.remote,
    p.salary,
    p.posted_month
from {{ ref('stg_postings') }} p
left join {{ ref('dim_company') }} c on c.company_name = p.company_name
