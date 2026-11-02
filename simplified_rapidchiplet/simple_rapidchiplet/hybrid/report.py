"""Reviewable, reproducible results from the shared physical oracle."""
from __future__ import annotations

import csv
from dataclasses import asdict
import html
import json
import math
from pathlib import Path


def clean_json(value):
    if isinstance(value,dict):
        return {str(key):clean_json(item) for key,item in value.items()}
    if isinstance(value,(list,tuple)):
        return [clean_json(item) for item in value]
    if isinstance(value,float) and not math.isfinite(value):
        return None
    return value


def write_json(path,data):
    path = Path(path)
    path.parent.mkdir(parents=True,exist_ok=True)
    temporary = path.with_suffix(path.suffix+'.tmp')
    temporary.write_text(json.dumps(clean_json(data),ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
    temporary.replace(path)


def package_svg(package,path):
    """Code-native vector diagram preserving physical placement proportions."""
    scale,margin = 24,28
    width = max(node.x_mm+node.width_mm for node in package.nodes.values())*scale+2*margin
    height = max(node.y_mm+node.height_mm for node in package.nodes.values())*scale+2*margin
    result = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width:.1f}" height="{height:.1f}" viewBox="0 0 {width:.1f} {height:.1f}">',
              '<rect width="100%" height="100%" fill="white"/>']
    def center(ident):
        node = package.nodes[ident]
        return margin+(node.x_mm+node.width_mm/2)*scale,margin+(node.y_mm+node.height_mm/2)*scale
    for link in package.links:
        a,b = center(link.a),center(link.b)
        color = '#188445' if link.kind in ('io_mesh','compute_mesh') else '#8795a4'
        result.append(f'<line data-link="{html.escape(link.a)}|{html.escape(link.b)}" x1="{a[0]}" y1="{a[1]}" x2="{b[0]}" y2="{b[1]}" stroke="{color}" stroke-width="2"/>')
    for ident,node in package.nodes.items():
        x,y,w,h = margin+node.x_mm*scale,margin+node.y_mm*scale,node.width_mm*scale,node.height_mm*scale
        fill = {'compute':'#d9eaf8','io':'#bde2cb','memory':'#ffe3a2'}[node.role]
        result.append(f'<rect data-node="{html.escape(ident)}" x="{x}" y="{y}" width="{w}" height="{h}" fill="{fill}" stroke="#233548"/>')
        result.append(f'<text pointer-events="none" x="{x+w/2}" y="{y+h/2}" text-anchor="middle" dominant-baseline="middle" font-family="Arial" font-size="9">{html.escape(ident)}</text>')
    result.append('</svg>')
    Path(path).write_text('\n'.join(result),encoding='utf-8')


def save_evaluation(folder,evaluation,evaluator,plan,*,search=None,planning=None,arguments=None,trace=False):
    folder = Path(folder)
    folder.mkdir(parents=True,exist_ok=True)
    write_json(folder/'summary.json',{'metrics':evaluation.metrics,'arguments':arguments or {},
               'planning':planning,'search':None if search is None else {key:search.to_dict()[key]
                    for key in ('method','seed','best_cost','evaluations') if key in search.to_dict()},
               'interpretation':'uncalibrated analytical estimates, not measured silicon or cycle-accurate RTL'})
    write_json(folder/'mapping.json',plan.to_dict())
    write_json(folder/'hardware.json',asdict(evaluator.hardware))
    write_json(folder/'network.json',evaluator.context.to_dict())
    write_json(folder/'package.json',evaluator.package.to_dict())
    from .hardware import FIXED_CHIPLET_PROFILE, GEMINI_CHIPLET_PROFILE
    write_json(folder/'deployment.json',{
        'chiplet_profile':GEMINI_CHIPLET_PROFILE if evaluator.hardware.package_topology == 'gemini_mesh' else FIXED_CHIPLET_PROFILE if evaluator.hardware.package_topology == 'compute_mesh' else 'legacy_indm_partition',
        'compute_chiplets':len(evaluator.package.compute_ids),'io_chiplets':len(evaluator.package.io_ids),
        'memory_dies':len(evaluator.package.memory_ids),'total_dies':len(evaluator.package.nodes),
        'mesh_rows':evaluator.hardware.cluster_rows,'mesh_cols':evaluator.hardware.cluster_cols,
        'package_topology':evaluator.hardware.package_topology,'routing':'deterministic XY (X then Y)',
        'placement_file':'package.json','mapping_file':'mapping.json','traffic_file':'traffic_routes.json',
        'timeline_file':'timeline.csv','per_chiplet':evaluator.hardware.to_dict(),
        'interpretation':'recommended deployment within the searched counts/budgets; analytical placement, not fabricated floorplan',
    })
    write_json(folder/'workload.json',evaluator.workload.to_dict())
    write_json(folder/'buffers.json',evaluation.buffer_statistics)
    if 'diagnostics' in evaluation.metrics:
        write_json(folder/'diagnostics.json',getattr(evaluation,'diagnostics',None) or evaluation.metrics['diagnostics'])
    from .patterns import layer_switch_evidence
    write_json(folder/'layer_switching.json',layer_switch_evidence(evaluation))
    if evaluation.communication is not None:
        events = {event.job.id:event for event in evaluation.schedule.events}
        stats = {row['id']:row for row in evaluation.transfer_statistics}
        routes = []
        for transfer in evaluation.communication.transfers:
            event = events[transfer.id]
            routes.append({**asdict(transfer),
                'routes':[{'destination':dst,'path':evaluator.context.route(transfer.src,dst)} for dst in transfer.dsts],
                'start_s':event.start_s,'finish_s':event.finish_s,'statistics':stats[transfer.id]})
        write_json(folder/'traffic_routes.json',{'routing':'XY','transfers':routes,
                   'note':'logical multicast shares each directed edge once; transit dies do not store the tensor in UB'})
    package_svg(evaluator.package,folder/'package.svg')
    from .visualization import save_layout
    save_layout(folder,evaluator,plan,evaluation)
    if search is not None:
        write_json(folder/'search.json',search.to_dict())
    if evaluation.schedule is not None:
        with (folder/'timeline.csv').open('w',newline='',encoding='utf-8') as stream:
            writer = csv.writer(stream)
            writer.writerow(('id','kind','start_s','finish_s','resources','dependencies','energy_j'))
            for event in evaluation.schedule.events:
                writer.writerow((event.job.id,event.job.kind,event.start_s,event.finish_s,
                                 '|'.join(event.job.resources),'|'.join(event.job.dependencies),event.job.energy_j))
        with (folder/'link_traffic.csv').open('w',newline='',encoding='utf-8') as stream:
            writer = csv.writer(stream)
            writer.writerow(('transfer','kind','source','destination','bytes'))
            for transfer in evaluation.transfer_statistics:
                for link in transfer['link_load_bytes']:
                    writer.writerow((transfer['id'],transfer['kind'],link['source'],link['destination'],link['bytes']))
        if trace:
            # NDJSON streams large traces without materializing a second huge
            # Python tree. Each record retains exact ownership/dependencies.
            with (folder/'trace.ndjson').open('w',encoding='utf-8') as stream:
                for kind,objects in (('unit',evaluation.compiled.units),('transfer',evaluation.communication.transfers)):
                    for item in objects:
                        stream.write(json.dumps({'record':kind,**asdict(item)},ensure_ascii=False)+'\n')
                for event in evaluation.schedule.events:
                    stream.write(json.dumps({'record':'event',**event.to_dict()},ensure_ascii=False)+'\n')
                for unit_id,service in evaluation.core_services.items():
                    stream.write(json.dumps({'record':'core_service','unit_id':unit_id,**service},ensure_ascii=False)+'\n')
    return folder
