"""Catalog identity shared by software permalinks and related-media owners."""

SOFTWARE_KEY_SQL = """md5(jsonb_build_array(system.manufacturer_name, system.system_name,
    title.cluster_key, software.identity_basis, software.source_snapshot_key,
    software.source_software_id, software.source_group_key)::text)"""
