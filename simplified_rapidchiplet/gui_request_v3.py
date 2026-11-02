"""Pure, isolated v0.2 GUI intent resolution; historical v1/v2 stay intact."""
from copy import deepcopy


SEARCH_PROFILES_V3 = {
    'fast': {'budget': 32, 'max_wall_time_s': 180., 'evaluation_timeout_s': 90.},
    'standard': {'budget': 128, 'max_wall_time_s': 1800., 'evaluation_timeout_s': 300.},
    'deep': {'budget': 256, 'max_wall_time_s': 3600., 'evaluation_timeout_s': 600.},
}
V3_KEYS = {'ui_schema_version', 'models', 'preference', 'batch', 'seed', 'search_mode', 'budget_mode',
           'budget', 'max_power', 'max_area', 'max_latency_ms', 'strict_power', 'strict_area', 'strict_latency',
           'workload_mode', 'fusion_mode', 'microbatch_mode', 'architecture_mode'}


def normalize_request_v3(raw, validate_v1):
    if not isinstance(raw, dict) or type(raw.get('ui_schema_version')) is not int or raw['ui_schema_version'] != 3:
        raise ValueError('v0.2 GUI requires ui_schema_version=3')
    if set(raw) - V3_KEYS:
        raise ValueError('unknown UI v3 fields: ' + ', '.join(sorted(set(raw) - V3_KEYS)))
    if type(raw.get('batch', 1)) is not int or raw.get('batch', 1) != 1:
        raise ValueError('v0.2 GUI requires Batch=1')
    for key, expected in (('workload_mode', 'single'), ('fusion_mode', 'auto'),
                          ('microbatch_mode', 'auto'), ('architecture_mode', 'auto')):
        if raw.get(key, expected) != expected:
            raise ValueError('v0.2 requires ' + key + '=' + expected)
    mode, budget_mode = raw.get('search_mode', 'standard'), raw.get('budget_mode', 'auto')
    if mode not in SEARCH_PROFILES_V3 or budget_mode not in ('auto', 'manual'):
        raise ValueError('unsupported v0.2 search/budget mode')
    bounds = deepcopy(SEARCH_PROFILES_V3[mode])
    if budget_mode == 'manual':
        if type(raw.get('budget')) is not int or not 1 <= raw['budget'] <= 512:
            raise ValueError('manual full-query ceiling must be an integer in 1..512')
        bounds['budget'] = raw['budget']
    elif 'budget' in raw:
        raise ValueError('Auto cannot also specify numeric budget')
    inputs = {key: deepcopy(value) for key, value in raw.items() if key in {
        'models', 'preference', 'seed', 'max_power', 'max_area', 'max_latency_ms',
        'strict_power', 'strict_area', 'strict_latency'}}
    inputs.setdefault('models', ['resnet18'])
    validated = validate_v1({**inputs, 'batch': 1, 'budget': bounds['budget']})
    # The historical validator is used only for input types and PPA preferences.
    # Its old 8MiB UB and core-related engine defaults never enter v0.2 config.
    config = {key: deepcopy(validated[key]) for key in (
        'models', 'preference', 'seed', 'max_power', 'max_area', 'max_latency_ms',
        'strict_power', 'strict_area', 'strict_latency')}
    config.update(bounds, engine_profile='gui04_v3', hardware_profile='chiplet_single_pe_array_v0_2',
        ui_schema_version=3, batch=1, microbatch_size=1, search_mode=mode, budget_mode=budget_mode,
        input_size=224, horizon=12, fusion_depth=4, checkpoint_every=1, render_images=False,
        seed_method='single_array_tangram_style_adapter_v1', report_format='text_numeric_tables',
        suite_wall_time_s=bounds['max_wall_time_s'] * len(config['models']),
        architecture_templates=[f'single_array_c{count}_{rows}x{count//rows}' for count in (1, 2, 4, 8, 16)
                                for rows in range(1, count + 1) if count % rows == 0])
    return config, {'ui_schema_version': 3, 'auto_resolved': True, 'requested': deepcopy(raw),
                    'effective_engine_config': deepcopy(config), 'resolver_version': 'gui04_v3_single_array_r1',
                    'microbatch_candidates': [1], 'profile_status': 'uncalibrated analytical model, finite search budget',
                    'capabilities': {'arbitrary_floorplan': False, 'arbitrary_routing': False, 'C10_local_partition_DP': False}}
