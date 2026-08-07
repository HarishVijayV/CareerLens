-- Deliberately a plain md5() surrogate key instead of pulling in the dbt_utils package
-- for one function — fewer moving parts for a learning project. Swap for
-- dbt_utils.generate_surrogate_key once you're comfortable adding packages.yml.
select
    md5(company_name) as company_id,
    company_name
from {{ ref('stg_postings') }}
where company_name is not null
group by company_name
