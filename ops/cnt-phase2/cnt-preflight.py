#!/usr/bin/env python3
"""Read-only CNT host capacity gate. Run ON THE HOST, never inside a container.

Default (new-host) mode: no Docker inspection, environment dump, provisioning,
process changes or file deletion. It requires the full CNT allocation plus
headroom on top of the current 1-minute load average.

Opt-in replacement mode (`--replace-existing`, or CNT_PREFLIGHT_MODE=replace-existing)
assesses an IN-PLACE replacement of the already-running production CNT sender.
It never relaxes the memory/disk/shm/configuration gates. It replaces only the
load-average CPU gate with a measured one: host /proc/stat busy time and the
existing CNT container's cgroup cpu.stat usage over the SAME bounded windows,
giving non-CNT demand (max across windows). It passes only when
    planned CNT_CPUS + max non-CNT cores + host reserve (>=1) + margin <= cores
and the existing CNT identity and a single running sender are positively
verified. Only read-only `docker ps`/`docker inspect` are executed. Any missing
metric or unavailable command fails closed.
"""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

REPLACE_MODE = "replace-existing"
DEFAULT_PROJECT = "epic-cnt-transport"
DEFAULT_SERVICE = "cnt"
DEFAULT_CONTAINER = "epic-cnt-capture"


def assess(sample, env, cpu_gate=True):
    memory = int(env.get("CNT_MEMORY_MB", "3072"))
    cpu = float(env.get("CNT_CPUS", "2"))
    reserve = int(env.get("CNT_HOST_RESERVE_MB", "1024"))
    disk = int(env.get("CNT_MIN_DISK_GB", "12"))
    shm = int(env.get("CNT_SHM_MB", "1024"))
    if memory < 2048 or cpu < 1 or reserve < 512 or disk < 8 or not 64 <= shm <= memory // 2:
        return ["unsafe_resource_configuration"]
    failures = []
    if sample["available_mb"] < memory + reserve: failures.append("insufficient_available_memory")
    if sample["disk_free_gb"] < disk: failures.append("insufficient_disk_headroom")
    if sample["cpus"] < cpu + 1: failures.append("insufficient_cpu_count")
    if cpu_gate and sample["load1"] > sample["cpus"] - cpu: failures.append("insufficient_cpu_headroom")
    if sample["containerized"]: failures.append("must_run_on_host")
    return failures


def sample_host(root):
    values = {}
    for line in Path("/proc/meminfo").read_text().splitlines():
        parts = line.split()
        if parts[0] in ("MemAvailable:", "SwapFree:"):
            values[parts[0].rstrip(":").lower()] = int(parts[1]) // 1024
    shm = shutil.disk_usage("/dev/shm")
    return {"available_mb": values.get("memavailable", 0), "swap_free_mb": values.get("swapfree", 0),
            "disk_free_gb": round(shutil.disk_usage(root).free / 1024 ** 3, 2),
            "shm_free_mb": shm.free // 1048576, "shm_total_mb": shm.total // 1048576,
            "cpus": os.cpu_count() or 1, "load1": os.getloadavg()[0],
            "containerized": Path("/.dockerenv").exists() or Path("/run/.containerenv").exists()}


# ---------- replacement mode: identity ----------

def replace_config(env):
    """Bounded, validated replacement settings. Raises ValueError when unsafe."""
    c = {"project": env.get("CNT_REPLACE_PROJECT", DEFAULT_PROJECT),
         "service": env.get("CNT_REPLACE_SERVICE", DEFAULT_SERVICE),
         "container": env.get("CNT_REPLACE_CONTAINER", DEFAULT_CONTAINER),
         "image_id": env.get("CNT_REPLACE_EXPECTED_IMAGE_ID", ""),
         "windows": int(env.get("CNT_CPU_WINDOWS", "3")),
         "window_s": float(env.get("CNT_CPU_WINDOW_SECONDS", "10")),
         "host_reserve_cores": float(env.get("CNT_HOST_RESERVE_CORES", "1")),
         "margin_cores": float(env.get("CNT_CPU_SAFETY_MARGIN_CORES", "0.5"))}
    if not c["image_id"].startswith("sha256:") or len(c["image_id"]) != 71:
        raise ValueError("expected_image_id_required")
    if not (3 <= c["windows"] <= 10 and 5 <= c["window_s"] <= 60):
        raise ValueError("unsafe_window_configuration")
    if c["host_reserve_cores"] < 1 or c["margin_cores"] < 0.25:
        raise ValueError("unsafe_reserve_configuration")
    return c


def verify_identity(conf, run):
    """run(args)->stdout. Returns (container_id|None, failures, facts)."""
    failures, facts = [], {}
    try:
        # Every running CNT-service sender, in ANY compose project, plus name matches.
        by_service = [l for l in run(["docker", "ps", "--no-trunc", "--filter",
                      f"label=com.docker.compose.service={conf['service']}",
                      "--format", "{{.ID}}\t{{.Names}}\t{{.Label \"com.docker.compose.project\"}}"]).splitlines() if l.strip()]
        by_name = [l for l in run(["docker", "ps", "--no-trunc", "--filter", f"name={conf['container']}",
                   "--format", "{{.ID}}\t{{.Names}}"]).splitlines() if l.strip()]
    except (OSError, subprocess.SubprocessError):
        return None, ["docker_unavailable"], facts
    ids = {l.split("\t")[0] for l in by_service + by_name}
    facts["running_cnt_senders"] = len(ids)
    if len(ids) != 1:
        return None, ["cnt_sender_count_not_one" if ids else "existing_cnt_not_running"], facts
    cid = ids.pop()
    try:
        info = json.loads(run(["docker", "inspect", cid]))[0]
    except (OSError, subprocess.SubprocessError, ValueError, IndexError, KeyError):
        return None, ["docker_inspect_unavailable"], facts
    labels = (info.get("Config") or {}).get("Labels") or {}
    checks = {
        "name_matches": info.get("Name", "").lstrip("/") == conf["container"],
        "project_matches": labels.get("com.docker.compose.project") == conf["project"],
        "service_matches": labels.get("com.docker.compose.service") == conf["service"],
        "image_matches": info.get("Image") == conf["image_id"],
        "running": (info.get("State") or {}).get("Running") is True,
        "pid_present": int((info.get("State") or {}).get("Pid") or 0) > 0,
    }
    facts.update(checks)
    for key, ok in checks.items():
        if not ok: failures.append("existing_cnt_" + key.replace("_matches", "_mismatch").replace("running", "not_running").replace("pid_present", "pid_missing"))
    return (cid if not failures else None), failures, facts


# ---------- replacement mode: measured CPU ----------

def read_proc_stat(text):
    """Return (total_jiffies, idle_jiffies) for the aggregate cpu line (idle+iowait idle)."""
    for line in text.splitlines():
        p = line.split()
        if p and p[0] == "cpu":
            v = [int(x) for x in p[1:]]
            if len(v) < 5: raise ValueError("proc_stat_short")
            # guest/guest_nice are already included in user/nice
            total = sum(v[:8]) if len(v) >= 8 else sum(v)
            return total, v[3] + v[4]
    raise ValueError("proc_stat_missing")


def read_cpu_stat_usec(text):
    for line in text.splitlines():
        p = line.split()
        if len(p) == 2 and p[0] == "usage_usec": return int(p[1])
    raise ValueError("cgroup_usage_missing")


def cgroup_paths(cid):
    return [f"/sys/fs/cgroup/system.slice/docker-{cid}.scope/cpu.stat",
            f"/sys/fs/cgroup/docker/{cid}/cpu.stat"]


def measure_cpu(conf, cpus, read, clock=time.monotonic, sleep=time.sleep, cid=""):
    """Sample host and CNT over identical windows. read(path)->text. Raises ValueError/OSError."""
    path = next((p for p in cgroup_paths(cid) if _exists(read, p)), None)
    if path is None: raise ValueError("cgroup_cpu_stat_unavailable")
    windows = []
    prev = (clock(), *read_proc_stat(read("/proc/stat")), read_cpu_stat_usec(read(path)))
    for _ in range(conf["windows"]):
        sleep(conf["window_s"])
        cur = (clock(), *read_proc_stat(read("/proc/stat")), read_cpu_stat_usec(read(path)))
        elapsed, d_total, d_idle, d_usec = cur[0] - prev[0], cur[1] - prev[1], cur[2] - prev[2], cur[3] - prev[3]
        if elapsed <= 0 or d_total <= 0 or d_idle < 0 or d_usec < 0: raise ValueError("cpu_counter_invalid")
        host = (d_total - d_idle) / d_total * cpus
        cnt = d_usec / 1e6 / elapsed
        if cnt > cpus * 1.05: raise ValueError("cpu_counter_inconsistent")
        windows.append({"host_busy_cores": round(host, 3), "cnt_cores": round(cnt, 3),
                        "other_cores": round(max(0.0, host - cnt), 3)})
        prev = cur
    return windows


def _exists(read, path):
    try:
        read(path); return True
    except OSError:
        return False


def assess_replacement_cpu(windows, cpus, planned, conf):
    max_other = max(w["other_cores"] for w in windows)
    max_cnt = max(w["cnt_cores"] for w in windows)
    required = planned + max_other + conf["host_reserve_cores"] + conf["margin_cores"]
    result = {"cpus": cpus, "planned_cnt_cpus": planned, "max_other_cores": max_other,
              "max_existing_cnt_cores": max_cnt, "host_reserve_cores": conf["host_reserve_cores"],
              "margin_cores": conf["margin_cores"], "required_cores": round(required, 3)}
    failures = []
    if required > cpus: failures.append("insufficient_measured_cpu_capacity")
    if max_cnt > planned * 0.9: failures.append("planned_cnt_cpu_below_observed_demand")
    result["reason"] = ("passed: planned+other+reserve+margin <= cores" if not failures
                        else "failed: " + ",".join(failures))
    return failures, result


def run_replacement(sample, env, run, read, clock=time.monotonic, sleep=time.sleep):
    failures = assess(sample, env, cpu_gate=False)
    report = {"mode": REPLACE_MODE, "sample": sample}
    try:
        conf = replace_config(env)
    except ValueError as e:
        return failures + [str(e)], report
    if "unsafe_resource_configuration" in failures:
        return failures, report
    cid, idf, facts = verify_identity(conf, run)
    report["identity"] = facts
    if idf: return failures + idf, report
    try:
        windows = measure_cpu(conf, sample["cpus"], read, clock, sleep, cid)
    except (OSError, ValueError) as e:
        return failures + ["cpu_metrics_unavailable"], {**report, "cpu_error": str(e)[:60]}
    report["windows"] = windows
    # The sender must still be the same single container after sampling.
    cid2, idf2, _ = verify_identity(conf, run)
    if idf2 or cid2 != cid: return failures + ["cnt_identity_changed_during_sampling"], report
    cpuf, report["cpu"] = assess_replacement_cpu(windows, sample["cpus"], float(env.get("CNT_CPUS", "2")), conf)
    return failures + cpuf, report


def _run(args):
    return subprocess.run(args, check=True, capture_output=True, text=True, timeout=15).stdout


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    replace = "--replace-existing" in argv or os.environ.get("CNT_PREFLIGHT_MODE") == REPLACE_MODE
    args = [a for a in argv if not a.startswith("--")]
    try:
        sample = sample_host(args[0] if args else "/var/lib/docker")
        if replace:
            failures, report = run_replacement(sample, os.environ, _run, lambda p: Path(p).read_text())
            print(json.dumps({"channel": "cnt", **report, "failures": failures,
                              "ready_for_replacement_review": not failures}))
        else:
            failures = assess(sample, os.environ)
            print(json.dumps({"channel": "cnt", "sample": sample, "failures": failures,
                              "ready_for_capacity_review": not failures}))
        return 1 if failures else 0
    except (OSError, ValueError, KeyError):
        print('{"channel":"cnt","failures":["preflight_unavailable"]}')
        return 1


if __name__ == "__main__":
    sys.exit(main())