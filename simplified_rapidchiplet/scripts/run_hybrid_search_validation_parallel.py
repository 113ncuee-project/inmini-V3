"""Run independent seed workers, then merge source-identical validation data.

Parallel workers share no policy, oracle cache or output files. Simulated PPA
is deterministic; elapsed times are measured under concurrent CPU contention.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys
import time


SCRIPT = Path(__file__).with_name("run_hybrid_search_validation.py")


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, allow_nan=False), encoding="utf-8")
    temporary.replace(path)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--budgets", default="64,128")
    parser.add_argument("--seeds", default="7,8,9")
    parser.add_argument("--methods", default="rl,random,greedy,sa")
    parser.add_argument("--proposals", default="uniform,cluster_guided")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    seeds = tuple(int(seed) for seed in args.seeds.split(","))
    if not seeds or len(set(seeds)) != len(seeds):
        parser.error("seeds must be distinct")
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    logs = out / "worker_logs"
    logs.mkdir(exist_ok=True)
    processes, streams, folders, last_lines = [], [], [], {}
    try:
        for index, seed in enumerate(seeds):
            # Keep the first worker's existing same-source checkpoints in place.
            folder = out if index == 0 else out.with_name(out.name + f"_seed{seed}")
            folders.append(folder)
            command = [sys.executable, str(SCRIPT), "--budgets", args.budgets, "--seeds", str(seed),
                       "--methods", args.methods, "--proposals", args.proposals, "--out", str(folder)]
            if args.resume:
                command.append("--resume")
            stream = (logs / f"seed{seed}.log").open("w", encoding="utf-8")
            streams.append(stream)
            processes.append(subprocess.Popen(command, stdout=stream, stderr=subprocess.STDOUT,
                              creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)))
            print(f"Started independent seed{seed} worker pid={processes[-1].pid}", flush=True)
        while any(process.poll() is None for process in processes):
            for seed in seeds:
                log = logs / f"seed{seed}.log"
                lines = log.read_text(encoding="utf-8", errors="replace").splitlines()
                if lines and lines[-1] != last_lines.get(seed):
                    last_lines[seed] = lines[-1]
                    print(f"worker{seed}: {lines[-1]}", flush=True)
            failed = [(seed, process.returncode) for seed, process in zip(seeds, processes)
                      if process.poll() not in (None, 0)]
            if failed:
                raise RuntimeError(f"validation workers failed: {failed}; inspect {logs}")
            time.sleep(1)
        if any(process.returncode != 0 for process in processes):
            raise RuntimeError("a validation worker exited unsuccessfully; prior reports will not be merged")
        reports = [json.loads((folder / "validation.json").read_text(encoding="utf-8")) for folder in folders]
        if any(not report.get("completed") for report in reports):
            raise RuntimeError("a worker did not complete its requested curves")
        for key in ("input_identity", "source_identity", "source_hashes", "methods", "proposals", "budgets"):
            if any(report[key] != reports[0][key] for report in reports[1:]):
                raise RuntimeError(f"worker provenance differs for {key}")
        if tuple(reports[0]["budgets"]) != tuple(map(int, args.budgets.split(","))):
            raise RuntimeError("workers did not produce the requested budget curves")
        merged = dict(reports[0])
        merged["seeds"] = seeds
        merged["trials"] = sorted([trial for report in reports for trial in report["trials"]],
                                  key=lambda trial: (trial["proposal"], trial["seed"], trial["method"]))
        keys = {(trial["proposal"], trial["seed"], trial["method"]) for trial in merged["trials"]}
        expected = len(seeds) * len(merged["methods"]) * len(merged["proposals"])
        if len(keys) != expected or len(keys) != len(merged["trials"]):
            raise RuntimeError("merged experiment is missing or duplicating a seed/method/proposal trial")
        merged["execution_parallelism"] = len(seeds)
        merged["wall_time_notes"] = "independent seed workers run concurrently; elapsed times include CPU contention and are not isolated method speed comparisons"
        merged["worker_folders"] = list(map(str, folders))
        save(out / "validation.json", merged)
        save(out / "inputs.json", {key: value for key, value in merged.items() if key != "trials"})
        print(f"Merged {len(keys)} source-identical trials: {out / 'validation.json'}", flush=True)
    finally:
        for process in processes:
            if process.poll() is None:
                process.terminate()
        for stream in streams:
            stream.close()


if __name__ == "__main__":
    main()
