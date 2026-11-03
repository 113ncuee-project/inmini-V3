"""Thin array adapter to the optional exact C++ calendar kernel."""
import ctypes
from functools import lru_cache
import hashlib
from pathlib import Path
import os
import numpy as np

SOURCE=Path(__file__).with_name('native_calendar.cpp')
def source_hash():return hashlib.sha256(SOURCE.read_bytes()).hexdigest()
def library_path():return SOURCE.parent/'_native'/('calendar_'+source_hash()[:16]+('.dll' if os.name=='nt' else '.so'))

@lru_cache(maxsize=1)
def library():
    path=library_path()
    if not path.exists():return None
    lib=ctypes.CDLL(str(path));d=ctypes.POINTER(ctypes.c_double);i=ctypes.POINTER(ctypes.c_int)
    lib.inmin_schedule.argtypes=[ctypes.c_int,ctypes.c_int,d,i,i,i,i,i,i,d,d,i]
    lib.inmin_schedule.restype=ctypes.c_int
    lib.inmin_slack.argtypes=[ctypes.c_int,ctypes.c_int,d,i,i,i,i,i,d,d,d]
    lib.inmin_slack.restype=ctypes.c_int
    return lib

def available():return library() is not None

def native_schedule(jobs):
    from .scheduler import Schedule,ScheduledJob
    jobs=tuple(jobs);n=len(jobs);by_id={j.id:k for k,j in enumerate(jobs)}
    if len(by_id)!=n:raise ValueError('duplicate job ID')
    priorities={p:k for k,p in enumerate(sorted({j.priority for j in jobs}))}
    names={name:k for k,name in enumerate(sorted(by_id))};resource_ids={}
    doff=[0];roff=[0];deps=[];resources=[]
    for job in jobs:
        for name in dict.fromkeys(job.dependencies):
            if name not in by_id or name==job.id:raise ValueError('unknown or self-referential job dependency')
            deps.append(by_id[name])
        doff.append(len(deps))
        for resource in job.resources:resources.append(resource_ids.setdefault(resource,len(resource_ids)))
        roff.append(len(resources))
    duration=np.asarray([j.duration_s for j in jobs],dtype=np.float64)
    arrays=[np.asarray(v,dtype=np.int32) for v in ([priorities[j.priority] for j in jobs],
        [names[j.id] for j in jobs],doff,deps,roff,resources)]
    starts=np.empty(n,dtype=np.float64);finishes=np.empty(n,dtype=np.float64);order=np.empty(n,dtype=np.int32)
    lib=library()
    if lib is None:raise RuntimeError('native scheduler not built; run scripts/build_native_calendar.py')
    dp=lambda a:a.ctypes.data_as(ctypes.POINTER(ctypes.c_double))
    ip=lambda a:a.ctypes.data_as(ctypes.POINTER(ctypes.c_int))
    code=lib.inmin_schedule(n,len(resource_ids),dp(duration),*(ip(a) for a in arrays),dp(starts),dp(finishes),ip(order))
    if code:raise ValueError('native schedule invalid dependency graph or allocation failure: '+str(code))
    events=[];busy={}
    for index in order:
        k=int(index);job=jobs[k];events.append(ScheduledJob(job,float(starts[k]),float(finishes[k])))
        for r in job.resources:busy[r]=busy.get(r,0.)+job.duration_s
    schedule=Schedule(tuple(events),max(finishes,default=0.),busy)
    schedule.validate()
    slack=np.empty(n,dtype=np.float64)
    code=lib.inmin_slack(n,len(resource_ids),dp(duration),ip(arrays[1]),ip(arrays[2]),ip(arrays[3]),
        ip(arrays[4]),ip(arrays[5]),dp(starts),dp(finishes),dp(slack))
    if code==0:object.__setattr__(schedule,'_cached_slack',{j.id:float(slack[k]) for k,j in enumerate(jobs)})
    return schedule
