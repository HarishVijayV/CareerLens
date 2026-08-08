-- Reads the bridge table instead of unnesting an array column, so this SQL runs
-- unchanged on Postgres AND Snowflake (array/flatten syntax differs between them;
-- plain rows don't).
select
    md5(skill)  as skill_id,
    skill       as skill_name,
    count(*)    as posting_count
from {{ source('raw', 'posting_skills') }}
where skill is not null
group by skill
