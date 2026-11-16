{#
  Use the configured schema as is. dbt's default would prefix it with the target schema
  (main_marts), which would differ between DuckDB and Snowflake.
#}
{% macro generate_schema_name(custom_schema_name, node) -%}
    {%- if custom_schema_name is none -%}
        {{ target.schema }}
    {%- else -%}
        {{ custom_schema_name | trim }}
    {%- endif -%}
{%- endmacro %}
