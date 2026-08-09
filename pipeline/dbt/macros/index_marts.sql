{#
  Index the mart tables the API actually queries.

  Why a macro and not hand-written SQL: a `table` materialisation is DROPped and rebuilt
  on every `dbt run`, and the index goes with it. An index created manually in psql works
  until the next pipeline run and then vanishes, which is the kind of regression nobody
  notices until search is slow again.

  Each index below exists because a specific query needed it — indexing "just in case"
  costs write time on every load and buys nothing:

    * bridge(posting_id)      the profile skill-match subquery looks up one posting's
                              skills per candidate row. Without it, that is a sequential
                              scan of 737k bridge rows PER ROW SCANNED.
    * dim_skill(skill_name)   both the skill filter and the skill-match join resolve a
                              name to an id.
    * fact(is_real, salary)   the default ordering of every search.
    * fact(region)            region filter and the profile region ranking.
    * fact(posting_id)        get_job, and the dbt uniqueness test.

  Snowflake has no CREATE INDEX — it uses micro-partitions instead — so this is guarded
  on the adapter. Running it there would fail the build for something Snowflake does not
  need.
#}
{% macro index_marts_tables() %}
  {% if target.type != 'postgres' %}
    {{ return('select 1') }}
  {% endif %}

  {% set table_name = this.identifier %}

  {% if table_name == 'fact_job_posting' %}
    create index if not exists ix_fact_real_salary
      on {{ this }} (is_real desc, salary desc nulls last);
    create index if not exists ix_fact_region on {{ this }} (region);
    create index if not exists ix_fact_posting_id on {{ this }} (posting_id);

  {% elif table_name == 'bridge_posting_skill' %}
    create index if not exists ix_bridge_posting on {{ this }} (posting_id);
    create index if not exists ix_bridge_skill on {{ this }} (skill_id);

  {% elif table_name == 'dim_skill' %}
    create index if not exists ix_dim_skill_name on {{ this }} (skill_name);

  {% elif table_name == 'dim_company' %}
    create index if not exists ix_dim_company_id on {{ this }} (company_id);

  {% else %}
    select 1
  {% endif %}
{% endmacro %}
