"""Named, dimensionless feature columns; mirrors rl_search.py schema3 ordering."""
def schema():
    state=['bias','log(latency/reference)','log(area/reference)','log(power/reference)','log(energy/reference)',
        'hard_violation_sum','PE_count/max_PE_count','groups/layers','fusion_stacks/groups','microbatch/batch',
        'compute_bottleneck_layer_fraction','network_bottleneck_layer_fraction','memory_bottleneck_layer_fraction',
        'episode_step/horizon','objective_cost','has_layer_diagnostics','mean_PE_utilization','mean_criticality',
        'max_link_queue_wait/latency','max_link_utilization','max_live_SRAM/capacity','max_DRAM_controller_busy/latency',
        'max_VPU_busy/latency','max_L2_RW_busy/latency']
    atoms=[f'contains_A{i}' for i in range(1,11)]; macros=[f'family_C{i}' for i in range(1,10)]
    local=['target_PE_count/source_PE_count-1','target_MACs/all_MACs','ordered_edits/4','A4_core_delta/source_PE_count',
        'log(B_new/B_old)','log(K_new/K_old)','log(H_new/H_old)','log(W_new/W_old)',
        'log(tile_H_new/old)','log(tile_W_new/old)','cache_H_flag','cache_V_flag','target_layers/all_layers',
        'is_composite','has_proxy_confidence','bias']
    candidate=atoms+macros+local+[a+'*'+s for s in state[1:6] for a in atoms]+['bias']
    candidate += [a+'*'+s for s in state[16:] for a in atoms]
    candidate += ['allocated_layers/all_layers','allocated_PE_sum/source_PE_count','new_groups/all_layers',
        'temporal_groups/new_groups','mean_K_partition/partition_product','mean_HW_partition/partition_product',
        'sink_tile_H/output_H','sink_tile_W/output_W','log(target_rows/source_rows)','log(target_cols/source_cols)',
        'target_IO/source_IO-1','sink_tile_area_fraction*max_memory_pressure','K_fraction*max_queue_wait/latency',
        'P_fraction*mean_PE_utilization']
    target=['max_target_criticality','target_MAC_service/(latency*unique_target_PEs)',
        'target_L1_service/(latency*unique_target_PEs)','target_VPU_busy/(latency*unique_target_dies)',
        'max_target_transfer_wait/latency','max_target_job_wait/latency','max_target_memory_pressure',
        'min_target_slack/latency','target_MACs/all_MACs','target_layers/all_layers','max_target_PE_utilization','missing_target_diagnostics']
    candidate += ['target/'+s for s in target]
    severity=[target[i] for i in (1,2,4,6)]
    candidate += [s+'*'+a for s in severity for a in atoms+macros]
    flows=['A12_output_stationary','A12_weight_reuse','A12_activation_reuse']
    candidate += flows+[s+'*'+f for s in severity for f in flows]
    assert len(state)==24 and len(candidate)==283
    return dict(schema_version=1,feature_schema='target_local_v3_normalized_v2',
        state=[dict(index=i,expression=n,unit='dimensionless') for i,n in enumerate(state)],
        candidate=[dict(index=i,expression=n,unit='dimensionless') for i,n in enumerate(candidate)],
        target=[dict(index=i,expression=n,unit='dimensionless') for i,n in enumerate(target)],
        clipping=[-8,8],
        sources={'state':'rl_search.state_features; current full-oracle metrics/reference/objective and mapping',
                 'candidate':'rl_search.candidate_features; explicit ordered edits plus current state; not future PPA',
                 'target':'target_bottleneck.target_features; current diagnostics layers; waits use max individual event, services divide by distinct target PEs/dies'},
        mask_off='zero state indices 10:13,16:24; empty target report (missing indicator remains); generator controlled separately',
        quality='partial analytic calendar attribution; shared pool pressure and whole-flow waits are not unique hardware causality; A9 observes all layers')
