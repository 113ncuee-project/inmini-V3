"""Explicit core lanes for the fixed Gemini hardware template.

The physical package graph aggregates two interfaces on a chiplet side for
geometry/native bump checks. This network restores each distinct lane for
workload routes, contention and energy; a flow never gets aggregate bandwidth.
"""
from dataclasses import replace
import math


def expand_core_network(spec, package, native):
    coords = {}
    for index,(row,col) in package.cluster_coordinates.items():
        for core in range(4):
            coords[f'compute:{index}/core:{core}']=(2*row+core//2,2*col+core%2)
    inverse={v:k for k,v in coords.items()}
    bandwidth=dict(native.link_bandwidth_Bps)
    ceilings=dict(native.native_link_bandwidth_Bps)
    lengths=dict(native.link_length_mm)
    energy=dict(native.link_energy_pj_per_bit)
    latencies={}
    for source,(row,col) in coords.items():
        for other in ((row+1,col),(row,col+1)):
            if other not in inverse: continue
            destination=inverse[other]
            a,b=source.split('/')[0],destination.split('/')[0]
            external=a!=b
            rate=spec.nop_bandwidth_Bps if external else spec.noc_bandwidth_Bps
            length=native.link_length_mm[(a,b)] if external else math.sqrt(spec.compute_area_mm2)/2
            # Native cross-die PHY/wire/router delay; local core hop is an
            # explicit architectural router+wire estimate at the NoC clock.
            delay=native.path_latency_ns[(a,b)] if external else (spec.compute_router_latency_cycles+length*spec.wire_latency_cycles_per_mm)/spec.noc_clock_hz*1e9
            for pair in ((source,destination),(destination,source)):
                bandwidth[pair]=rate; ceilings[pair]=rate; lengths[pair]=length
                energy[pair]=spec.nop_energy_pj_per_bit if external else spec.noc_energy_pj_per_bit
                latencies[pair]=delay
    for row in range(spec.cluster_rows):
        for flank in (0,1):
            io=f'io:{2*row+flank}'
            col=2*spec.cluster_cols-1 if flank else 0
            for lane in (0,1):
                core=inverse[(2*row+lane,col)]
                die=core.split('/')[0]
                for pair in ((io,core),(core,io)):
                    bandwidth[pair]=spec.nop_bandwidth_Bps
                    ceilings[pair]=spec.nop_bandwidth_Bps
                    lengths[pair]=native.link_length_mm[(io,die)]
                    energy[pair]=spec.nop_energy_pj_per_bit
                    latencies[pair]=native.path_latency_ns[(io,die)]
    for io,memory in zip(package.io_ids,package.memory_ids):
        for pair in ((io,memory),(memory,io)):
            latencies[pair]=native.path_latency_ns[pair]

    def endpoint_core(endpoint, lane):
        if endpoint in coords: return endpoint
        index=int(endpoint.split(':')[1])
        row,flank=divmod(index,2)
        return inverse[(2*row+lane,2*spec.cluster_cols-1 if flank else 0)]

    def route(source,destination):
        if source==destination: return (source,)
        if source.startswith(('memory:','io:')) and destination.startswith(('memory:','io:')) and source.split(':')[1]==destination.split(':')[1]:
            return (source,destination)
        # Controller can inject into either of the two real ingress routers.
        lane=(coords.get(destination,coords.get(source,(0,0)))[0])%2
        first,last=endpoint_core(source,lane),endpoint_core(destination,lane)
        path=[source]
        if source not in coords:
            io=f'io:{source.split(":")[1]}'
            if path[-1]!=io: path.append(io)
            path.append(first)
        row,col=coords[first]
        target_row,target_col=coords[last]
        while col!=target_col:
            col += 1 if target_col>col else -1
            path.append(inverse[(row,col)])
        while row!=target_row:
            row += 1 if target_row>row else -1
            path.append(inverse[(row,col)])
        if destination not in coords:
            io=f'io:{destination.split(":")[1]}'
            path.append(io)
            if destination!=io: path.append(destination)
        return tuple(path)

    endpoints=(*coords,*package.io_ids,*package.memory_ids)
    routes=dict(native.routes)
    path_latency=dict(native.path_latency_ns)
    for source in endpoints:
        for destination in endpoints:
            path=route(source,destination)
            if any(pair not in latencies for pair in zip(path,path[1:])):
                raise ValueError('Gemini core route traverses an absent lane')
            routes[(source,destination)]=path
            path_latency[(source,destination)]=sum(latencies[pair] for pair in zip(path,path[1:]))
    provenance={**native.provenance,
        'routing':'deterministic core-level XY, column first then row; distinct 2x2-core NoC and inter-chiplet D2D lanes; two IO ingress routers per side',
        'core_coordinates':{k:list(v) for k,v in coords.items()},
        'physical_aggregation':'package links bundle two D2D interfaces for native geometry; workload lanes each retain their single-interface capacity',
        'core_network_latency':'external links use native package PHY/wire/router delays; internal hops use core router cycles and estimated half-die wire length',
        'multicast':'one region copy per common directed core/IO link; separate destination GLB writes'}
    return replace(native,routes=routes,path_latency_ns=path_latency,link_bandwidth_Bps=bandwidth,
        native_link_bandwidth_Bps=ceilings,link_length_mm=lengths,link_energy_pj_per_bit=energy,
        provenance=provenance)
