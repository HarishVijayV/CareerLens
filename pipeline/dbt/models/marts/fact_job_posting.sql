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
    p.posted_month,
    -- Carried to the fact table so the API can rank and filter on provenance without
    -- joining back to staging. A real posting is one you can actually apply to; a
    -- synthetic one exists to give the pipeline volume. Conflating them in the UI would
    -- be the single most misleading thing this project could do.
    p.is_real,
    p.source,
    p.url,
    -- ML output joined in here, which is what turns the model from a training script
    -- into a product feature: every posting carries what the model thinks it SHOULD pay
    -- and how far the advertised salary sits from that.
    s.predicted_salary,
    s.salary_vs_market,
    coalesce(s.pay_band, 'unknown') as pay_band
from {{ ref('stg_postings') }} p
left join {{ ref('dim_company') }} c on c.company_name = p.company_name
-- LEFT JOIN deliberately: a posting with no salary can't be scored, and it must still
-- appear in the fact table. An inner join here would silently delete rows.
left join {{ source('raw', 'posting_scores') }} s on s.posting_id = p.posting_id
