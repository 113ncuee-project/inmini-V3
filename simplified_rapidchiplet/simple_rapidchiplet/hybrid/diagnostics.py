"""Evidence-backed bottleneck reports from the executed analytical schedule.

Waiting is measured against each job's actual dependency release. A multicast
job reserves its route atomically, so its aggregate queue delay cannot be
uniquely attributed to DRAM/NoC/D2D; those split fields deliberately stay null.
"""
from collections import defaultdict
import heapq
import math

from .hardware import physical_endpoint
from .scheduler import peak_interval_bytes


def compact_diagnostics(report):
    """Stable scalar-search diagnostics, independent of trace retention."""
    return {**report,'flows':report['flows'][:128],
        'flows_truncated':report['flows_truncated'] or len(report['flows'])>128,
        'network':[{**row,'flow_ids':row['flow_ids'][:32],
                    'time_windows':row['time_windows'][:32],
                    'time_windows_truncated':row['time_windows_truncated'] or len(row['time_windows'])>32}
                   for row in report['network']]}


def _schedule_slack(schedule):
    """Latest starts in the actual dependency and resource-order DAG."""
    if hasattr(schedule,'_cached_slack'):return schedule._cached_slack
    events=schedule.event_map
    predecessors={name:set(e.job.dependencies) for name,e in events.items()}
    calendars=defaultdict(list)
    for e in schedule.events:
        if e.finish_s>e.start_s:
            for resource in e.job.resources: calendars[resource].append(e)
    for spans in calendars.values():
        spans.sort(key=lambda e:(e.start_s,e.finish_s,e.job.id))
        for a,b in zip(spans,spans[1:]): predecessors[b.job.id].add(a.job.id)
    successors={name:set() for name in events}
    counts={name:len(deps) for name,deps in predecessors.items()}
    for name,deps in predecessors.items():
        for dep in deps: successors[dep].add(name)
    ready=[n for n,c in counts.items() if not c]; heapq.heapify(ready)
    order=[]
    while ready:
        name=heapq.heappop(ready); order.append(name)
        for child in successors[name]:
            counts[child]-=1
            if counts[child]==0: heapq.heappush(ready,child)
    if len(order)!=len(events):
        return {name:None for name in events}
    latest={}
    for name in reversed(order):
        finish=min((latest[child] for child in successors[name]),default=schedule.makespan_s)
        latest[name]=finish-events[name].job.duration_s
    return {name:max(0.0,latest[name]-event.start_s) for name,event in events.items()}


def build_diagnostics(workload, hardware, package, compiled, communication,
                      schedule, services, transfer_stats, buffers, metrics, context, *, detailed=True):
    events=schedule.event_map
    units=compiled.unit_map
    transfers=communication.transfer_map
    slack=_schedule_slack(schedule)
    tolerance=max(1e-15,schedule.makespan_s*1e-8)
    release={name:max((events[dep].finish_s for dep in e.job.dependencies),default=0.0) for name,e in events.items()}
    queue={name:max(0.0,e.start_s-release[name]) for name,e in events.items()}
    rows_by_layer=defaultdict(list)
    for unit in compiled.units: rows_by_layer[unit.layer_id].append(unit)
    transfer_by_layer=defaultdict(set)
    for t in communication.transfers:
        for name in (*t.producer_units,*t.consumer_units):
            if name in units: transfer_by_layer[units[name].layer_id].add(t.id)
    layers=[]
    for layer in workload.layers:
        rows=rows_by_layer[layer.id]
        own=[events[name] for u in rows for name in (f'read:{u.id}',f'compute:{u.id}',u.id)]
        compute=[events[f'compute:{u.id}'] for u in rows]
        active_cores=sorted({u.chiplet for u in rows})
        start=min((e.start_s for e in own),default=0.0)
        finish=max((e.finish_s for e in own),default=0.0)
        compute_time=sum(services[u.id]['compute_s'] for u in rows)
        compute_busy=sum(e.job.duration_s for e in compute)
        read_busy=sum(events[f'read:{u.id}'].job.duration_s for u in rows)
        write_busy=sum(events[u.id].job.duration_s for u in rows)
        input_wait=0.0
        for u in rows:
            e=events[f'read:{u.id}']
            data=max((events[d].finish_s for d in e.job.dependencies if d in transfers),default=0.0)
            control=max((events[d].finish_s for d in e.job.dependencies if d not in transfers),default=0.0)
            input_wait+=max(0.0,data-control)
        min_slack=min((slack[e.job.id] for e in own if slack[e.job.id] is not None),default=None)
        critical=min_slack is not None and min_slack<=tolerance
        macs=sum(u.macs for u in rows)
        utilization=macs/(hardware.per_core_mac_rate*compute_time) if compute_time else 0.0
        resource_wait=sum(queue[e.job.id] for e in own)
        network_wait=sum(queue[t] for t in transfer_by_layer[layer.id])
        network_busy=sum(events[t].job.duration_s for t in transfer_by_layer[layer.id])
        parallelism=math.prod(workload.tensor_map[layer.output].shape)
        # Conservative signals, not a proof that adding cores improves PPA.
        bottleneck='unknown'
        evidence=[]
        if critical and compute_time>=2*(read_busy+write_busy) and utilization>=0.5 and resource_wait<=compute_busy:
            bottleneck='compute'; evidence=['critical schedule path','compute dominates local stages','integer-kernel utilization >= 0.5']
        elif critical and network_wait>compute_busy:
            bottleneck='network'; evidence=['critical schedule path','observed atomic transfer queue delay exceeds compute service']
        layers.append({'layer_id':layer.id,'allocated_cores':active_cores,'resource_count':len(active_cores),
            'schedule_start_s':start,'schedule_finish_s':finish,'schedule_span_s':finish-start,
            'compute_busy_s':compute_busy,'compute_service_s':compute_time,
            'local_read_busy_s':read_busy,'local_write_busy_s':write_busy,
            'input_wait_s':input_wait,'input_wait_definition':'sum of additional dependency-release delay from input transfers after non-transfer dependencies are ready; can overlap other units',
            'resource_wait_s':resource_wait,'transfer_queue_wait_s':network_wait,
            'transfer_service_s':network_busy,
            'dram_wait_s':None,'noc_wait_s':None,'d2d_wait_s':None,
            'wait_attribution':'unknown: atomic multicast reserves all route resources; split attribution is unsupported',
            'slack_s':min_slack,'criticality':1.0 if critical else 0.0,
            'compute_utilization':utilization,'MACs':macs,
            'output_parallel_elements':parallelism,'has_parallelism':parallelism>len(active_cores),
            'bottleneck':bottleneck,'bottleneck_evidence':evidence})
    flow_rows=[]
    link_windows=defaultdict(list)
    link_bytes=defaultdict(int)
    link_flow_ids=defaultdict(list)
    for row in transfer_stats:
        t=transfers[row['id']]; e=events[t.id]
        route_rows=[]
        for link in row['link_load_bytes']:
            a,b,amount=link['source'],link['destination'],link['bytes']
            kind=('dram' if a.startswith('memory:') or b.startswith('memory:') else
                  'noc' if a.startswith('compute:') and b.startswith('compute:') and physical_endpoint(a)==physical_endpoint(b) else 'd2d')
            pair=(a,b); link_bytes[pair]+=amount; link_flow_ids[pair].append(t.id)
            window={'start_s':e.start_s,'finish_s':e.finish_s,'transmitted_bytes':amount,
                    'reserved_duration_s':e.job.duration_s,'queue_wait_s':queue[t.id],'flow_id':t.id}
            link_windows[pair].append(window)
            route_rows.append({**link,'kind':kind,'capacity_Bps':context.link_bandwidth_Bps[pair]})
        flow_rows.append({'flow_id':t.id,'tensor_id':t.tensor,'tensor_range':t.region.bounds,
            'producer_units':t.producer_units,'consumer_units':t.consumer_units,
            'source':t.src,'destinations':t.dsts,'payload_bytes':t.bytes,
            'transmitted_bytes':sum(x['bytes'] for x in row['link_load_bytes']),
            'segments':route_rows,'type':t.kind,
            'traffic_semantics':'multicast common directed edge counted once; destination GLBs each store their own copy',
            'dependency_ready_s':release[t.id],'start_s':e.start_s,'finish_s':e.finish_s,
            'queue_wait_s':queue[t.id],'service_s':e.job.duration_s,
            'slack_s':slack[t.id],'energy_j':row['energy_j']})
    network=[]
    for pair in sorted(link_windows):
        spans=link_windows[pair]
        busy=sum(x['reserved_duration_s'] for x in spans)
        duration=schedule.makespan_s
        capacity=context.link_bandwidth_Bps[pair]
        network.append({'source':pair[0],'destination':pair[1],
            'capacity_Bps':capacity,'transmitted_bytes':link_bytes[pair],
            'reserved_busy_s':busy,'reservation_fraction':busy/duration if duration else 0.0,
            'payload_service_s':link_bytes[pair]/capacity,
            'queue_wait_s':sum(x['queue_wait_s'] for x in spans),
            'queue_wait_attribution':'shared atomic-route delay; can appear on several involved links and must not be summed over links',
            'flow_ids':link_flow_ids[pair] if detailed else link_flow_ids[pair][:32],
            'time_windows':spans if detailed else spans[:32],
            'time_windows_truncated':not detailed and len(spans)>32})
    # Named residency intervals expose actual simultaneous peaks. Components'
    # individual peaks need not occur at the same instant and are not additive.
    component_intervals=defaultdict(lambda:defaultdict(list))
    for u in compiled.units:
        accumulator=u.output_region.elements*hardware.psum_bytes if u.macs else u.output_bytes
        component_intervals[u.chiplet]['psum'].append((events[f'compute:{u.id}'].start_s,events[u.id].finish_s,accumulator))
    for t in communication.transfers:
        for destination in t.dsts:
            if not destination.startswith('compute:'): continue
            last=max((events[u].finish_s for u in t.consumer_units if units[u].chiplet==destination),default=events[t.id].finish_s)
            component='weight' if t.kind=='dram_weight' else 'cache' if t.kind=='df_cache_copy' else 'activation'
            component_intervals[destination][component].append((events[t.id].finish_s,last,t.bytes))
    memory=[]
    for core in package.mapping_core_ids:
        memory.append({'core_id':core,
            'peak_live_bytes':buffers.get('global_buffer_peak_by_core',{}).get(core),
            'capacity_bytes':hardware.core_global_buffer_bytes or None,
            'component_peak_bytes':{name:peak_interval_bytes(component_intervals[core][name]) for name in ('weight','activation','psum','cache')},
            'component_policy':'component peaks are individual and non-additive; total capacity check also retains produced outputs and forwarded copies',
            'scratch_peak_bytes':buffers['local_scratch_peak_by_core'].get(core),
            'spill_bytes':0,'spill_policy':'unsupported: capacity overflow is infeasible; no hidden DRAM spill/reload',
            'bank_accesses':{name:{key:sum(s.get('traffic_evidence',{}).get('sram_access_ledger',{}).get(name,{}).get(key,0) for u,s in services.items() if units[u].chiplet==core)
                                      for key in ('read_bits','write_bits')} for name in ('WL1','AL1','OL1','UB')}})
    stacks=[]
    stack_statistics=(compiled.execution_statistics or {}).get('stacks',[])
    for index,stack in enumerate(compiled.plan.fusion_stacks):
        evidence=stack_statistics[index] if index<len(stack_statistics) else {}
        sink=stack.layer_ids[-1]
        tile_types=defaultdict(int)
        for unit in rows_by_layer[sink]:
            tile_types[str(tuple(unit.output_region.shape[2:]))]+=1
        copies=[t for t in communication.transfers if t.kind=='df_cache_copy' and
                any(units[u].layer_id in stack.layer_ids for u in (*t.producer_units,*t.consumer_units))]
        stacks.append({'stack_id':f'stack:{index}','layer_ids':stack.layer_ids,'tile_hw':stack.tile_hw,
            'overlap':stack.overlap,'tile_types':dict(tile_types),'execution_statistics':evidence,
            'per_stack_recompute_MACs':evidence.get('recompute_macs'),
            'cache_cross_core_read_bytes':sum(t.bytes for t in copies),
            'cache_cross_core_write_bytes':sum(t.bytes*len(t.dsts) for t in copies),
            'per_stack_cache_reads_bytes':None,'per_stack_cache_writes_bytes':None,
            'available_capacity_bytes_per_core':hardware.core_global_buffer_bytes or None,
            'status':'executed/unique/recompute MACs are compiler-derived; separate on-core overlap-cache accesses within aggregate GLB accesses are unknown'})
    flow_rows.sort(key=lambda f:(-(f['queue_wait_s']+f['service_s']),f['flow_id']))
    return {'version':'bottleneck_report_v1','source':'executed analytical resource-calendar schedule',
        'system':{key:metrics[key] for key in ('architecture_candidate_id','compute_chiplets','io_chiplets','total_chiplets','memory_dies','total_dies','area_mm2','energy_j','energy_per_sample_j','latency_s','throughput_samples_s','power_w','power_definition','feasible','violations')},
        'layers':layers,'flows':flow_rows if detailed else flow_rows[:128],
        'flows_truncated':not detailed and len(flow_rows)>128,
        'network':network,'memory':memory,'df_stacks':stacks,
        'overlap_semantics':'global latency is scheduled makespan; compute/read/write/transfer busy time and waits may overlap across units and must not be summed into latency',
        'critical_path_semantics':'slack uses DAG dependencies plus the actual scheduled resource order; specific to this schedule, not a globally optimal reschedule',
        'unsupported':['packet/virtual-channel arbitration','uniquely split DRAM/NoC/D2D waiting','automatic buffer spill','peak power/TDP','physical signoff']}
