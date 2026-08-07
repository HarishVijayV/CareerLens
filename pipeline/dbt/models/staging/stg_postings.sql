-- Thin staging layer: rename/cast only, no business logic yet. Every mart model below
-- builds on this instead of the raw source directly, so if a raw column ever gets
-- renamed upstream, there's exactly one model to fix.
select
    posting_id,
    trim(title)            as title,
    company                as company_name,
    location,
    region,
    seniority,
    remote,
    salary_clean            as salary,
    required_skills,        -- array column; exploded into dim_skill below
    posted_month
from {{ source('raw', 'postings') }}
where posting_id is not null
