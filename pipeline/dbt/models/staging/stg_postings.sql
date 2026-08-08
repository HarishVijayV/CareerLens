-- Thin staging layer: rename and cast only, no business logic. Every mart model builds
-- on this rather than on the raw source directly, so a renamed upstream column means
-- fixing exactly one model instead of five.
select
    posting_id,
    trim(title)     as title,
    company         as company_name,
    location,
    region,
    seniority,
    remote,
    salary_clean    as salary,
    posted_month
from {{ source('raw', 'postings') }}
where posting_id is not null
