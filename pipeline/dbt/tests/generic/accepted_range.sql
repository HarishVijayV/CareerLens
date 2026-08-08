{#
  Custom generic test: fails for any row whose value falls outside [min_value, max_value].

  dbt_utils ships one of these, but writing it yourself is worth the ten lines — a dbt
  test is simply a SELECT that returns the OFFENDING rows. Zero rows returned = test
  passes. Once that clicks, you can write a test for any business rule you can express
  in SQL, which is far more useful than memorizing which package has which helper.

  Usage in schema.yml:
      tests:
        - accepted_range:
            min_value: 0
            max_value: 2000000
#}
{% test accepted_range(model, column_name, min_value, max_value) %}

select {{ column_name }}
from {{ model }}
where {{ column_name }} is not null
  and ({{ column_name }} < {{ min_value }} or {{ column_name }} > {{ max_value }})

{% endtest %}
