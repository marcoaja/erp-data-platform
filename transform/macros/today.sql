{#
  The current UTC calendar day. A macro so that unit tests can pin "today" with an override;
  the DuckDB profile and the Snowflake profile both run the session in UTC.
#}
{% macro today() -%}
    cast({{ dbt.current_timestamp() }} as date)
{%- endmacro %}
