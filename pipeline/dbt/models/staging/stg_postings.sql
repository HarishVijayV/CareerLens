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
    posted_month,
    -- Provenance, and a good example of why a staging layer earns its keep.
    --
    -- This arrives as TEXT holding 'True', not a boolean: the synthetic generator emits no
    -- is_real field at all, so the loader sees a column that is NULL for 147k rows and a
    -- Python bool for 5k, and widens it to text. Casting here means exactly one model
    -- knows about that quirk — every mart downstream just reads a boolean.
    --
    -- NULL means synthetic (the column didn't exist when those rows were written), so the
    -- coalesce is load-bearing, not defensive padding.
    coalesce(lower(is_real::text) in ('true', 't', '1'), false) as is_real,
    source,
    url
from {{ source('raw', 'postings') }}
where posting_id is not null
