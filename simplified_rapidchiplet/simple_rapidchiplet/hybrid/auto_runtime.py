"""Cancellable local-process wrapper around the unchanged full PPA evaluator.

One persistent process preserves exact microkernel caches. Parent-side deadlines
can stop a single evaluation; a partial response is never an evaluated design.
"""
from pathlib import Path
from types import SimpleNamespace
from dataclasses import asdict
import json,os,pickle,subprocess,sys,time,uuid

def atomic_json(path,value):
    from .report import clean_json
    p=Path(path);p.parent.mkdir(parents=True,exist_ok=True)
    tmp=p.with_name(p.name+'.'+uuid.uuid4().hex+'.tmp')
    tmp.write_text(json.dumps(clean_json(value),ensure_ascii=False,allow_nan=False),encoding='utf-8')
    for attempt in range(10):
        try:tmp.replace(p);return
        except PermissionError:
            if attempt==9:raise
            time.sleep(min(.2,.02*2**attempt))

class EvaluationTimeout(TimeoutError):pass

def read_completed_response(path,deadline):
    """Windows scanners may briefly lock even an atomically published file."""
    while True:
        try:return json.loads(Path(path).read_text(encoding='utf-8'))
        except PermissionError:
            if time.monotonic()>=deadline:
                raise EvaluationTimeout('completed response remained locked until deadline; no partial PPA accepted')
            time.sleep(.02)

class BoundedOraclePool:
    def __init__(self,workload,folder,*,deadline,evaluation_timeout_s):
        self.workload=workload;self.folder=Path(folder).resolve();self.folder.mkdir(parents=True,exist_ok=True)
        with (self.folder/'workload.pkl').open('wb') as f:pickle.dump(workload,f)
        self.deadline=deadline;self.evaluation_timeout_s=evaluation_timeout_s
        self.process=None;self.log=None;self.records=[];self.full_evaluations=0;self.cache_hits=0

    def _start(self):
        if self.process is not None and self.process.poll() is None:return
        app=Path(__file__).resolve().parents[2]
        env=os.environ.copy();env['PYTHONPATH']=str(app)+os.pathsep+env.get('PYTHONPATH','')
        self.log=(self.folder/'worker.log').open('ab')
        self.process=subprocess.Popen([sys.executable,'-u','-m','simple_rapidchiplet.hybrid.auto_runtime','--worker',str(self.folder)],
            cwd=app,env=env,stdin=subprocess.PIPE,stdout=self.log,stderr=self.log,
            creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))

    def request(self,operation,*,deadline=None,timeout_s=None,**payload):
        end=min(self.deadline,deadline if deadline is not None else self.deadline)
        cap=self.evaluation_timeout_s if timeout_s is None else timeout_s
        remaining=min(cap,end-time.monotonic())
        if remaining<=0:raise EvaluationTimeout('deadline reached before '+operation)
        self._start();ident=uuid.uuid4().hex;response=self.folder/(ident+'.json')
        started=time.monotonic();row={'id':ident,'operation':operation,'status':'running','timeout_s':remaining,
            'phase':payload.get('phase','archive' if operation=='persist' else 'unspecified'),'architecture':payload.get('architecture'),
            'owned_launcher_pid':self.process.pid}
        self.records.append(row);atomic_json(self.folder/'accounting.json',self.records)
        try:
            self.process.stdin.write((json.dumps({'operation':operation,'response':str(response),**payload})+'\n').encode('utf-8'))
            self.process.stdin.flush()
            while not response.is_file():
                if time.monotonic()-started>=remaining:
                    self.close();row['status']='timeout';raise EvaluationTimeout('full evaluator '+operation+' exceeded '+f'{remaining:.3f}s; no partial PPA accepted')
                if self.process.poll() is not None:
                    raise RuntimeError('isolated oracle exited; inspect '+str(self.folder/'worker.log'))
                time.sleep(.02)
            try:result=read_completed_response(response,started+remaining)
            except EvaluationTimeout:
                self.close();row['status']='timeout';raise
            try:response.unlink()  # completed scratch; durable archives/trace/accounting are separate
            except PermissionError:row['scratch_cleanup_deferred']=True
            row.update(status=result['status'],full_evaluations=result.get('full_evaluations',0),
                       cache_hits=result.get('cache_hits',0),evaluation_elapsed_s=result.get('evaluation_elapsed_s',0))
            self.full_evaluations+=result.get('full_evaluations',0);self.cache_hits+=result.get('cache_hits',0)
            if result['status']!='complete':
                if result.get('error_type')=='ValueError':raise ValueError(result['error'])
                raise RuntimeError(result['error'])
            return result
        finally:
            row['elapsed_s']=time.monotonic()-started
            if row['status']=='running':row['status']='error'
            atomic_json(self.folder/'accounting.json',self.records)

    def evaluate(self,candidate,plan,*,deadline=None,phase='rl'):
        return self.request('evaluate',deadline=deadline,architecture=candidate.id,
                            hardware=asdict(candidate.hardware),mapping=plan.to_dict(),phase=phase)

    def persist(self,candidate,plan,folder,config):
        return self.request('persist',timeout_s=max(.1,min(15,self.deadline-time.monotonic()-2)),
                            architecture=candidate.id,mapping=plan.to_dict(),folder=str(Path(folder).resolve()),config=config)

    def close(self):
        if self.process is not None:
            if self.process.poll() is None:
                # Windows venv python.exe can be a launcher with a real Python
                # child. Stop the owned tree, not just that redirector.
                if os.name=='nt':
                    subprocess.run(['taskkill','/PID',str(self.process.pid),'/T','/F'],
                        stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=5,
                        creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
                if self.process.poll() is None:self.process.kill()
            if self.process.stdin is not None:
                try:self.process.stdin.close()
                except OSError:pass
            self.process.wait(timeout=5);self.process=None
        if self.log is not None:self.log.close();self.log=None

def worker(folder):
    from .evaluator import HybridEvaluator
    from .hardware import HardwareSpec
    from .search import plan_from_dict
    from .report import save_evaluation
    folder=Path(folder)
    with (folder/'workload.pkl').open('rb') as f:workload=pickle.load(f)
    atomic_json(folder/'worker_started.json',{'worker_pid':os.getpid(),'parent_pid':os.getppid()})
    evaluators={};last=None
    for line in sys.stdin.buffer:
        req=json.loads(line);started=time.monotonic();full=hits=0
        try:
            key=req['architecture'];plan=plan_from_dict(req['mapping'])
            if req['operation']=='evaluate':
                if key not in evaluators:evaluators[key]=HybridEvaluator(workload,HardwareSpec.from_dict(req['hardware']),trace=True)
                e=evaluators[key];before=e.evaluations;old_hits=e.cache_hits
                result=e.evaluate(plan,retain_trace=True)
                full=e.evaluations-before;hits=e.cache_hits-old_hits
                last=(key,req['mapping'],result,e)
                # Completed archives are persisted independently. Keep bounded
                # trace memory, while retaining the shared exact kernel cache.
                for item in evaluators.values():item.cache.clear()
                value={'metrics':result.metrics}
            elif req['operation']=='persist':
                if last is None or last[:2]!=(key,req['mapping']):raise ValueError('persist must refer to the last completed exact evaluation')
                _,_,result,e=last
                save_evaluation(req['folder'],result,e,plan,arguments=req['config'],
                    planning={'method':'GUI04 multi-start Tangram + transactional RL','trace_source':'completed full evaluation; no report replay'})
                value={'folder':req['folder'],'metrics':result.metrics}
            else:raise ValueError('unknown oracle operation')
            atomic_json(req['response'],{'status':'complete','full_evaluations':full,'cache_hits':hits,
                'evaluation_elapsed_s':time.monotonic()-started,**value})
        except Exception as exc:
            atomic_json(req['response'],{'status':'error','error_type':type(exc).__name__,'error':type(exc).__name__+': '+str(exc),
                'full_evaluations':full,'cache_hits':hits,'evaluation_elapsed_s':time.monotonic()-started})

if __name__=='__main__':
    if len(sys.argv)!=3 or sys.argv[1]!='--worker':raise SystemExit('internal worker entry only')
    worker(sys.argv[2])
