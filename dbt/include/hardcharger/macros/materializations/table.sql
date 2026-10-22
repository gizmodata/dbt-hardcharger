{% materialization table, adapter='hardcharger', supported_languages=['sql', 'python'] %}

  {%- set language = model['language'] -%}
  {%- set existing_relation = load_cached_relation(this) -%}
  {%- set target_relation = this.incorporate(type='table') %}
  {%- set intermediate_relation = make_intermediate_relation(target_relation) -%}
  {%- set preexisting_intermediate_relation = load_cached_relation(intermediate_relation) -%}
  {%- set backup_relation_type = 'table' if existing_relation is none else existing_relation.type -%}
  {%- set backup_relation = make_backup_relation(target_relation, backup_relation_type) -%}
  {%- set preexisting_backup_relation = load_cached_relation(backup_relation) -%}
  {% set grant_config = config.get('grants') %}

  {{ drop_relation_if_exists(preexisting_intermediate_relation) }}
  {{ drop_relation_if_exists(preexisting_backup_relation) }}

  {{ run_hooks(pre_hooks, inside_transaction=False) }}
  {{ run_hooks(pre_hooks, inside_transaction=True) }}

  -- build model
  {% if language == 'python' %}
    {% call statement('main', language='python', fetch_result=False) -%}
      {{ py_write_table(temporary=False, relation=intermediate_relation, compiled_code=compiled_code) }}
    {%- endcall %}
  {% else %}
    {% call statement('main') -%}
      {{ get_create_table_as_sql(False, intermediate_relation, sql) }}
    {%- endcall %}
  {% endif %}

  {% do create_indexes(intermediate_relation) %}

  -- cleanup
  {% if existing_relation is not none %}
    {% set existing_relation = load_cached_relation(existing_relation) %}
    {% if existing_relation is not none %}
      {{ adapter.rename_relation(existing_relation, backup_relation) }}
    {% endif %}
  {% endif %}

  {{ adapter.rename_relation(intermediate_relation, target_relation) }}

  {{ run_hooks(post_hooks, inside_transaction=True) }}

  {% set should_revoke = should_revoke(existing_relation, full_refresh_mode=True) %}
  {% do apply_grants(target_relation, grant_config, should_revoke=should_revoke) %}

  {% do persist_docs(target_relation, model) %}

  {{ adapter.commit() }}

  {{ drop_relation_if_exists(backup_relation) }}

  {{ run_hooks(post_hooks, inside_transaction=False) }}

  {{ return({'relations': [target_relation]}) }}
{% endmaterialization %}


{% materialization incremental, adapter='hardcharger', supported_languages=['sql', 'python'] %}

  {% set language = model['language'] %}

  -- delegate to the default incremental materialization for SQL
  {% if language == 'sql' %}
    {% set result = dbt.materialization_incremental_default() %}
    {{ return(result) }}
  {% endif %}

  -- Python incremental
  {%- set existing_relation = load_cached_relation(this) -%}
  {%- set target_relation = this.incorporate(type='table') %}
  {%- set full_refresh_mode = (should_full_refresh() or (existing_relation is not none and existing_relation.is_view)) -%}
  {%- set unique_key = config.get('unique_key') -%}
  {%- set on_schema_change = incremental_validate_on_schema_change(config.get('on_schema_change'), default='ignore') -%}
  {%- set incremental_strategy = config.get('incremental_strategy') or 'default' -%}
  {%- set strategy_sql_macro_func = adapter.get_incremental_strategy_macro(context, incremental_strategy) -%}

  {#-- Ensure connection is open for commit --#}
  {%- call statement('setup_connection') -%}
    select 1
  {%- endcall -%}

  {% if existing_relation is none or full_refresh_mode %}
    {#-- First run or full refresh: drop and create --#}
    {{ drop_relation_if_exists(existing_relation) }}
    {% call statement('main', language='python', fetch_result=False) -%}
      {{ py_write_table(temporary=False, relation=target_relation, compiled_code=compiled_code) }}
    {%- endcall %}
  {% else %}
    {#-- Incremental run: create temp table, then merge/append into target --#}
    {%- set tmp_relation = make_temp_relation(target_relation) -%}
    {% call statement('main', language='python', fetch_result=False) -%}
      {{ py_write_table(temporary=True, relation=tmp_relation, compiled_code=compiled_code) }}
    {%- endcall %}

    {#-- Use the same schema handling and strategy dispatch as SQL models. --#}
    {%- set contract_config = config.get('contract') -%}
    {% if not contract_config or not contract_config.enforced %}
      {% do adapter.expand_target_column_types(from_relation=tmp_relation, to_relation=target_relation) %}
    {% endif %}
    {%- set dest_columns = process_schema_changes(on_schema_change, tmp_relation, existing_relation) -%}
    {% if not dest_columns %}
      {#-- With ignore, retain historical target columns absent from this extract.
           Write the shared columns by name instead of requiring identical shapes. --#}
      {%- set source_column_names = adapter.get_columns_in_relation(tmp_relation) | map(attribute='name') | map('lower') | list -%}
      {%- set dest_columns = [] -%}
      {% for column in adapter.get_columns_in_relation(existing_relation) %}
        {% if column.name | lower in source_column_names %}
          {% do dest_columns.append(column) %}
        {% endif %}
      {% endfor %}
    {% endif %}
    {%- set incremental_predicates = config.get('predicates', none) or config.get('incremental_predicates', none) -%}
    {%- set strategy_arg_dict = {
      'target_relation': target_relation,
      'temp_relation': tmp_relation,
      'unique_key': unique_key,
      'dest_columns': dest_columns,
      'incremental_predicates': incremental_predicates
    } -%}
    {%- call statement('incremental_apply') -%}
      {{ strategy_sql_macro_func(strategy_arg_dict) }}
    {%- endcall -%}
    {%- call statement('cleanup_temp') -%}
      DROP TABLE IF EXISTS {{ tmp_relation }}
    {%- endcall -%}
  {% endif %}

  {% do persist_docs(target_relation, model) %}
  {{ adapter.commit() }}

  {{ return({'relations': [target_relation]}) }}
{% endmaterialization %}
