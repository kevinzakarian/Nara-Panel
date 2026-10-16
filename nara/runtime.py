import copy
import json
import os
import shutil
import socket
import subprocess
import threading
import time
from pathlib import Path
from . import stats
from .config import build_config, client_config, eligible, require, validate


def atomic_write(path, content):
    path = Path(path)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with open(temporary, "w", encoding="utf-8", opener=lambda p, f: os.open(p, f, 0o600)) as f:
        f.write(content)
        f.flush()
        os.fsync(f.fileno())
    os.replace(temporary, path)


class Runtime:
    def __init__(self, store, binary="sing-box", stats_port=10085):
        self.store, self.binary, self.stats_port = store, binary, stats_port
        self.lock = threading.RLock()
        self.process = None
        self.log_file = None
        self.active = store.get("active")
        self.baseline = {}
        self.last_stats = None
        self.stats_error = ""
        self.failures = 0
        self.error = ""
        self.started = None
        self.shutdown = threading.Event()
        self.run_dir = store.directory / "runtime"
        self.run_dir.mkdir(exist_ok=True, mode=0o700)
        self.generation = None

    @property
    def running(self):
        return self.process is not None and self.process.poll() is None

    def version(self):
        if not shutil.which(self.binary):
            return None
        try:
            return subprocess.run([self.binary, "version"], capture_output=True, text=True, timeout=5).stdout.splitlines()[0]
        except (OSError, subprocess.SubprocessError, IndexError):
            return None

    def collect(self):
        counters = stats.query(self.stats_port)
        deltas = []
        for name, value in counters.items():
            parts = name.split(">>>")
            if len(parts) != 4 or parts[0] != "user" or not parts[1].startswith("client-") or parts[2] != "traffic":
                continue
            direction = {"uplink": "upload", "downlink": "download"}.get(parts[3])
            if not direction:
                continue
            previous = self.baseline.get(name, 0)
            require(value >= previous, "Traffic counter reset unexpectedly")
            deltas.append((parts[1][7:], direction, value - previous))
        self.store.add_traffic(deltas)
        self.baseline = counters
        self.last_stats = time.time()
        self.stats_error = ""
        self.failures = 0

    def prepare(self, state, totals=None):
        validate(state)
        require(all(i["port"] != self.stats_port for i in state["inbounds"]), "An inbound cannot use the statistics API port")
        require(shutil.which(self.binary), "Sing-box core is not installed or is not in PATH")
        import uuid
        generation = self.run_dir / uuid.uuid4().hex
        generation.mkdir(mode=0o700)
        try:
            for t in state["tls"]:
                atomic_write(generation / (t["id"] + ".crt"), t["certificate"])
                atomic_write(generation / (t["id"] + ".key"), t["private_key"])
            usage = self.store.totals() if totals is None else totals
            # Check inactive and unassigned inbounds too, without opening their ports.
            checked_config = build_config(state, usage, generation, self.stats_port, check_all=True)
            self.check_config(checked_config, generation, "inbound / DNS")
            if state["inbounds"]:
                probe = copy.deepcopy(state)
                probe["settings"]["server_address"] = probe["settings"].get("server_address") or "127.0.0.1"
                for inbound in probe["inbounds"]:
                    inbound["enabled"] = True
                user = {"id": "validation", "uuid": "00000000-0000-4000-8000-000000000001",
                        "password": "validation-only-not-a-real-user", "enabled": True,
                        "inbound_ids": [i["id"] for i in probe["inbounds"]]}
                self.check_config(client_config(probe, user, {}), generation, "client export")
            config = build_config(state, usage, generation, self.stats_port)
            atomic_write(generation / "config.json", json.dumps(config, indent=2))
            return generation, config
        except Exception:
            shutil.rmtree(generation, ignore_errors=True)
            raise

    def check_config(self, config, generation, label):
        path = generation / "check.json"
        atomic_write(path, json.dumps(config, indent=2))
        checked = subprocess.run([self.binary, "check", "-c", str(path)],
                                 capture_output=True, text=True, timeout=30)
        if checked.returncode:
            # Diagnostics may contain credentials. Keep them in the private directory.
            with open(self.store.directory / "core.log", "a", opener=lambda p, f: os.open(p, f, 0o600)) as log:
                log.write("Validation failed (" + label + "):\n" + checked.stderr[-16000:] + "\n")
            raise ValueError("Sing-box rejected the " + label + " settings. Previous settings were kept; details are in the private core.log.")
        path.unlink(missing_ok=True)

    def launch(self, generation):
        try:
            with socket.create_connection(("127.0.0.1", self.stats_port), timeout=.3):
                raise ValueError("The statistics port is already in use")
        except (ConnectionRefusedError, TimeoutError):
            pass
        log_path = self.store.directory / "core.log"
        if log_path.exists() and log_path.stat().st_size > 2_000_000:
            log_path.unlink()
        self.log_file = open(log_path, "a", opener=lambda p, f: os.open(p, f, 0o600))
        self.process = subprocess.Popen([self.binary, "run", "-c", str(generation / "config.json")],
                                        stdout=self.log_file, stderr=self.log_file, start_new_session=True)
        self.baseline = {}
        deadline = time.monotonic() + 6
        while time.monotonic() < deadline:
            require(self.running, "Core exited during startup; check ports and certificates")
            try:
                self.collect()
                time.sleep(.15)
                require(self.running, "Core exited during startup")
                self.started = time.time()
                return
            except Exception:
                time.sleep(0.15)
        raise ValueError("Core statistics API is unavailable; build sing-box with with_v2ray_api")

    def stop(self, collect=True):
        if self.running:
            if collect:
                try:
                    self.collect()
                except Exception:
                    self.stats_error = "Final traffic statistics could not be collected before stopping"
            self.process.terminate()
            try:
                self.process.wait(timeout=8)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=3)
        if self.log_file:
            self.log_file.close()
            self.log_file = None
        self.process = None

    def apply(self, state, persist=True, save=False, reset_client=None):
        with self.lock:
            if self.running:
                self.collect()  # Keep the working core when accounting is unavailable.
            def usage():
                totals = self.store.totals()
                if reset_client:
                    totals[reset_client] = {"upload": 0, "download": 0}
                return totals
            generation, config = self.prepare(state, usage())
            old = self.generation
            was_running = self.running
            # Link rotation, notes, public URL, and equivalent edits need no restart.
            if save and was_running and old and not reset_client:
                expected = build_config(state, usage(), old, self.stats_port)
                certificates_match = all((old / (t["id"] + suffix)).exists() and
                    (old / (t["id"] + suffix)).read_text() == t[key]
                    for t in state["tls"] for suffix, key in ((".crt", "certificate"), (".key", "private_key")))
                if certificates_match and expected == json.loads((old / "config.json").read_text()):
                    try:
                        self.store.commit_configuration(state, save=True)
                        self.active = copy.deepcopy(state)
                    finally:
                        shutil.rmtree(generation, ignore_errors=True)
                    self.error = ""
                    return {"running": True, "inbounds": len(config["inbounds"]), "restarted": False}
            self.stop()
            try:
                # Final counters can cross a quota boundary while validation runs.
                config = build_config(state, usage(), generation, self.stats_port)
                atomic_write(generation / "config.json", json.dumps(config, indent=2))
                self.launch(generation)
                if persist:
                    self.store.commit_configuration(state, save=save, reset_client=reset_client)
            except Exception as exc:
                self.stop(collect=False)
                shutil.rmtree(generation, ignore_errors=True)
                self.error = str(exc)
                if was_running and old and self.active:
                    old_config = build_config(self.active, self.store.totals(), old, self.stats_port)
                    atomic_write(old / "config.json", json.dumps(old_config, indent=2))
                    try:
                        self.launch(old)
                    except Exception:
                        self.stop(collect=False)
                        self.error += "; rollback also failed"
                self.store.audit("Configuration apply failed; previous settings retained")
                raise ValueError(self.error)
            self.generation = generation
            self.active = copy.deepcopy(state)
            self.error = ""
            self.failures = 0
            for child in self.run_dir.iterdir():
                if child != generation and child.is_dir():
                    shutil.rmtree(child, ignore_errors=True)
            self.store.audit("Configuration applied and core started")
            return {"running": True, "inbounds": len(config["inbounds"]), "restarted": True}

    def status(self):
        return {"running": self.running, "version": self.version(), "started": self.started,
                "active_revision": self.active.get("revision") if self.active else None,
                "last_stats": self.last_stats, "stats_error": self.stats_error,
                "error": self.error, "stats_port": self.stats_port}

    def worker(self):
        if self.store.get("autostart") and self.active:
            try:
                self.apply(self.active)
            except Exception as exc:
                self.error = str(exc)
        while not self.shutdown.wait(5):
            with self.lock:
                if not self.running:
                    if self.process is not None:
                        self.error = "Core exited unexpectedly; review settings and start it again"
                        self.store.audit(self.error)
                        self.stop(collect=False)
                    continue
                try:
                    self.collect()
                except Exception:
                    self.failures += 1
                    self.stats_error = "Could not collect client traffic statistics"
                    if self.failures >= 3:
                        self.stop(collect=False)
                        self.error = "Core stopped because traffic accounting was unavailable; this prevents bypassing traffic limits"
                        self.store.audit(self.error)
                    continue
                if self.active and self.generation:
                    expected = build_config(self.active, self.store.totals(), self.generation, self.stats_port)
                    actual = json.loads((self.generation / "config.json").read_text())
                    if expected != actual:
                        try:
                            self.apply(self.active)
                        except Exception as exc:
                            self.stop(collect=False)
                            self.error = str(exc)


class Metrics:
    def __init__(self):
        self.previous_cpu = None
        self.previous_net = None
        self.samples = []

    def read(self, directory):
        result = {"hostname": socket.gethostname(), "platform": os.uname().sysname,
                  "cpu_percent": None, "memory_total": None, "memory_used": None,
                  "uptime": None, "rx_rate": None, "tx_rate": None,
                  "load": list(os.getloadavg()), "cpu_count": os.cpu_count()}
        disk = shutil.disk_usage(directory)
        result.update(disk_total=disk.total, disk_used=disk.used)
        try:
            lines = Path("/proc/stat").read_text().splitlines()
            cpu = [int(x) for x in lines[0].split()[1:9]]
            total, idle = sum(cpu), cpu[3] + cpu[4]
            if self.previous_cpu:
                delta = total - self.previous_cpu[0]
                result["cpu_percent"] = round(100 * (1 - (idle - self.previous_cpu[1]) / delta), 1) if delta else 0
            self.previous_cpu = total, idle
            mem = {l.split(":")[0]: int(l.split()[1]) * 1024 for l in Path("/proc/meminfo").read_text().splitlines()}
            result.update(memory_total=mem["MemTotal"], memory_used=mem["MemTotal"] - mem["MemAvailable"],
                          uptime=float(Path("/proc/uptime").read_text().split()[0]))
            rx = tx = 0
            for line in Path("/proc/net/dev").read_text().splitlines()[2:]:
                interface, values = line.split(":")
                if interface.strip() == "lo":
                    continue
                values = values.split()
                rx += int(values[0])
                tx += int(values[8])
            now = time.time()
            if self.previous_net:
                elapsed = max(now - self.previous_net[0], .001)
                result.update(rx_rate=max(0, (rx - self.previous_net[1]) / elapsed),
                              tx_rate=max(0, (tx - self.previous_net[2]) / elapsed))
                self.samples.append({"at": now, "rx": result["rx_rate"], "tx": result["tx_rate"]})
                self.samples = self.samples[-120:]
            self.previous_net = now, rx, tx
        except (OSError, KeyError, ValueError):
            pass  # Missing Linux metrics remain null; never substitute demonstration values.
        result["samples"] = self.samples
        return result
