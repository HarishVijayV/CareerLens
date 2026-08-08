-- Resolves the raw bridge rows to surrogate keys, so the star schema joins on ids
-- rather than raw strings. This is the many-to-many link between fact_job_posting and
-- dim_skill.
select distinct
    ps.posting_id,
    md5(ps.skill) as skill_id
from {{ source('raw', 'posting_skills') }} ps
inner join {{ ref('fact_job_posting') }} f on f.posting_id = ps.posting_id
where ps.skill is not null
