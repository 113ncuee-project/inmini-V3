"""Export standard Matplotlib figures from source-pinned validation results."""
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
import statistics

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np


ROOT = Path(__file__).resolve().parents[1]
COLORS = {'rl':'#176ca6','random':'#8c9095','greedy':'#cf7624','sa':'#318553'}


def save_figure(figure,path):
    figure.savefig(path,dpi=180,bbox_inches='tight')
    figure.savefig(path.with_suffix('.svg'),bbox_inches='tight')
    plt.close(figure)


def architecture_plot(folder,out):
    data = json.loads((folder/'experiment.json').read_text(encoding='utf-8'))
    rows = data['runs']
    labels = [Path(row['folder']).name.replace('multi_ring','ring').replace('dies','') for row in rows]
    figure,axes = plt.subplots(1,3,figsize=(13,4))
    for axis,key,scale,label in zip(axes,('area_mm2','latency_s','edp_js'),(1,1e6,1e9),
                                    ('Silicon area (mm²)','Batch latency (µs)','Batch EDP (nJ·s)')):
        bars = axis.bar(labels,[row['metrics'][key]*scale for row in rows],color=['#267eaa' if 'ring' in name else '#a88a58' for name in labels])
        axis.set_ylabel(label)
        axis.tick_params(axis='x',labelrotation=40)
        axis.grid(axis='y',alpha=.22)
        for bar,row in zip(bars,rows):
            if not row['metrics']['feasible']:
                bar.set_hatch('///')
    figure.suptitle('Equal compute/storage budget: 4 / 8 / 16 dies, ring vs mesh\nResidual toy, RL 16 queries per architecture; uncalibrated analytical model',fontsize=11)
    figure.tight_layout()
    save_figure(figure,out/'architecture.png')


def resnet_architecture_plot(path,out):
    data = json.loads(path.read_text(encoding='utf-8'))
    rows = data['runs']
    labels = [row['id'].replace('multi_ring','ring').replace('dies','') for row in rows]
    figure,axes = plt.subplots(1,3,figsize=(13,4))
    for axis,key,scale,label in zip(axes,('area_mm2','latency_s','edp_js'),(1,1e3,1e3),
                                    ('Silicon area (mm²)','Batch latency (ms)','Batch EDP (mJ·s)')):
        bars = axis.bar(labels,[row['metrics'][key]*scale for row in rows],color=['#267eaa' if 'ring' in name else '#a88a58' for name in labels])
        axis.set_ylabel(label)
        axis.tick_params(axis='x',labelrotation=40)
        axis.grid(axis='y',alpha=.22)
        for bar,row in zip(bars,rows):
            if not row['metrics']['feasible']:
                bar.set_hatch('///')
    figure.suptitle('Equal resource budget: full ResNet50 batch 1 across physical architectures\nSame balanced initialization protocol; uncalibrated analytical model',fontsize=11)
    figure.tight_layout()
    save_figure(figure,out/'resnet_architecture.png')


def mapping_plot(path,out):
    data = json.loads(path.read_text(encoding='utf-8'))
    rows = data['rows']
    figure,axes = plt.subplots(1,3,figsize=(13,4))
    labels = [row['name'].replace('batch','B').replace('_ub','\n').replace('_','\n') for row in rows]
    values = [[row['metrics']['latency_s']*1e3 for row in rows],
              [row['metrics']['energy_j']/(row['metrics']['microbatch_size']*row['metrics']['microbatch_count'])*1e3 for row in rows],
              [max(row['metrics']['buffer_peak_bytes'].values())/1024**2 for row in rows]]
    for axis,amounts,label in zip(axes,values,('Batch latency (ms)','Energy / sample (mJ)','Peak unified SRAM / die (MiB)')):
        bars = axis.bar(labels,amounts,color=['#267eaa' if row['metrics']['feasible'] else '#c8c8c8' for row in rows])
        for bar,row in zip(bars,rows):
            if not row['metrics']['feasible']:
                bar.set_hatch('///')
        axis.set_ylabel(label)
        axis.grid(axis='y',alpha=.22)
        axis.tick_params(axis='x',labelsize=8)
    capacities = [row.get('hardware',data['hardware'])['unified_buffer_bytes']/1024**2 for row in rows]
    axes[2].plot(range(len(rows)),capacities,color='#b84135',linestyle='none',marker='_',markersize=22,
                 markeredgewidth=2,label='Installed capacity for this row')
    axes[2].legend(fontsize=8)
    figure.suptitle('Full ResNet50: batch and capacity-backed exact-region weight retention\nHatched columns are infeasible diagnostics, excluded from gain comparisons; 4 MiB keeps the same mapping',fontsize=11)
    figure.tight_layout()
    save_figure(figure,out/'resnet_mapping.png')


def search_plot(path,out):
    data = json.loads(path.read_text(encoding='utf-8'))
    proposals = data['proposals']
    figure,axes = plt.subplots(1,len(proposals),figsize=(6*len(proposals),4),squeeze=False)
    for axis,proposal in zip(axes[0],proposals):
        for method in data['methods']:
            curves = [trial['curve'] for trial in data['trials'] if trial['proposal']==proposal and trial['method']==method]
            if not curves:
                continue
            budgets = sorted(set.intersection(*(set(row['budget'] for row in curve) for curve in curves)))
            means,errors = [],[]
            for budget in budgets:
                values = [next(row['best_cost_relative_to_initial'] for row in curve if row['budget']==budget) for curve in curves]
                means.append(statistics.mean(values))
                errors.append(statistics.stdev(values) if len(values)>1 else 0)
            axis.errorbar(budgets,means,yerr=errors,color=COLORS[method],label=method,marker='o',capsize=4)
        axis.set_title(proposal.replace('_',' '))
        axis.set_xlabel('Cumulative unique mapping evaluations')
        axis.set_ylabel('Best batch EDP / fixed initial batch EDP')
        axis.set_xticks(data['budgets'])
        axis.grid(alpha=.22)
        axis.legend()
    figure.suptitle('Learned RL vs identical-budget baselines: real physical oracle\nResidual toy; mean ± sample SD across three seeds; not a silicon measurement',fontsize=11)
    figure.tight_layout()
    save_figure(figure,out/'search_curves.png')


def timeline_plot(folder,out):
    summary = json.loads((folder/'summary.json').read_text(encoding='utf-8'))['metrics']
    busy = summary['resource_busy_s']
    chosen = []
    for prefix,count in (('memory:',2),('io:',2),('link:',2),('core:',3),('noc:',3)):
        chosen.extend(sorted((name for name in busy if name.startswith(prefix)),key=busy.get,reverse=True)[:count])
    with (folder/'timeline.csv').open(encoding='utf-8') as stream:
        rows = list(csv.DictReader(stream))
    figure,axis = plt.subplots(figsize=(12,5))
    for index,resource in enumerate(chosen):
        spans = [(float(row['start_s'])*1e6,(float(row['finish_s'])-float(row['start_s']))*1e6)
                 for row in rows if resource in row['resources'].split('|')]
        axis.broken_barh(spans,(index-.35,.7),facecolors='#267eaa' if not resource.startswith('core:') else '#e0953a')
    axis.set_yticks(range(len(chosen)),chosen,fontsize=8)
    axis.set_xlabel('Time (µs)')
    axis.grid(axis='x',alpha=.2)
    axis.set_title('Example actual dependency/resource calendar (selected busy resources)')
    figure.tight_layout()
    save_figure(figure,out/'timeline.png')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out',type=Path,default=ROOT/'results'/'hybrid_figures')
    parser.add_argument('--architectures',type=Path,default=ROOT/'results'/'hybrid_architectures_final')
    parser.add_argument('--mapping',type=Path,default=ROOT/'results'/'hybrid_mapping_capacity_validation.json')
    parser.add_argument('--resnet-architectures',type=Path,default=ROOT/'results'/'hybrid_resnet_architectures'/'comparison.json')
    parser.add_argument('--search',type=Path,default=ROOT/'results'/'hybrid_search_validation_final'/'validation.json')
    parser.add_argument('--timeline',type=Path,default=ROOT/'results'/'hybrid_toy_final')
    args = parser.parse_args()
    args.out.mkdir(parents=True,exist_ok=True)
    for check,operation in ((args.architectures/'experiment.json',lambda:architecture_plot(args.architectures,args.out)),
                            (args.mapping,lambda:mapping_plot(args.mapping,args.out)),
                            (args.resnet_architectures,lambda:resnet_architecture_plot(args.resnet_architectures,args.out)),
                            (args.search,lambda:search_plot(args.search,args.out)),
                            (args.timeline/'timeline.csv',lambda:timeline_plot(args.timeline,args.out))):
        if check.exists():
            operation()
    (args.out/'plot_runtime.json').write_text(json.dumps({'matplotlib':matplotlib.__version__,
                     'numpy':np.__version__,'plotter':'standard Matplotlib Agg; source JSON/CSV preserved'},indent=2),encoding='utf-8')


if __name__=='__main__':
    main()
