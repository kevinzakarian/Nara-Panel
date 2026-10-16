"""Stream build diagnostics, with bounded retries for transient downloads only."""
import argparse
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import threading
import time

TRANSIENT = re.compile(r'timeout|timed out|temporary failure|connection (?:reset|refused)|unexpected EOF|\bEOF\b|no such host|network is unreachable|TLS handshake|HTTP/2|INTERNAL_ERROR|(?:429|500|502|503|504) (?:Too|Internal|Bad|Service|Gateway)', re.I)
INTEGRITY = re.compile(r'checksum mismatch|SECURITY ERROR|verification failed|certificate.*(?:invalid|unknown|expired)|unknown revision', re.I)


def run_step(label, command, log, attempts=1, timeout=1800, delay=3, quiet_stdout=False):
    for attempt in range(1, attempts + 1):
        message = f'\n[NARA] {label} (attempt {attempt}/{attempts})\n'
        print(message, end='', flush=True)
        with open(log, 'a', encoding='utf-8') as output:
            output.write(message); output.flush()
            tail = []
            expired = threading.Event()
            process = subprocess.Popen(command, stdout=subprocess.DEVNULL if quiet_stdout else subprocess.PIPE,
                                       stderr=subprocess.PIPE if quiet_stdout else subprocess.STDOUT, text=True,
                                       errors='replace', start_new_session=True)
            def kill_group():
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            def terminate():
                expired.set()
                kill_group()
            timer = threading.Timer(timeout, terminate)
            timer.start()
            try:
                for line in (process.stderr if quiet_stdout else process.stdout):
                    print(line, end='', flush=True)
                    output.write(line); output.flush()
                    tail.append(line)
                    tail = tail[-100:]
                status = process.wait()
            finally:
                timer.cancel()
                if process.poll() is None:
                    kill_group()
                    process.wait()
                (process.stderr if quiet_stdout else process.stdout).close()
            if status == 0 and not expired.is_set():
                return 0
            diagnostics = ''.join(tail)
            retry = (expired.is_set() or TRANSIENT.search(diagnostics)) and not INTEGRITY.search(diagnostics)
            if retry and attempt < attempts:
                print('[NARA] Temporary download failure; retrying with the existing verified cache.', flush=True)
                time.sleep(delay * attempt)
                continue
            print(f'[NARA] {label} failed. Full diagnostics: {log}', file=sys.stderr, flush=True)
            if expired.is_set():
                print('[NARA] The operation exceeded its time limit.', file=sys.stderr)
            if re.search(r'out of memory|cannot allocate memory|signal: killed', diagnostics, re.I):
                print('[NARA] The build was killed or ran out of memory. Check server RAM and OOM logs; use a server with more available memory or configured swap.', file=sys.stderr)
            elif retry:
                print('[NARA] Check server DNS and access to proxy.golang.org, sum.golang.org and GitHub. A trusted GOPROXY may be supplied; checksum verification remains enabled.', file=sys.stderr)
            return status if 0 < status < 126 else 1
    return 1


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--quiet-stdout', action='store_true')
    parser.add_argument('--label', required=True)
    parser.add_argument('--log', type=Path, required=True)
    parser.add_argument('--attempts', type=int, default=1)
    parser.add_argument('--timeout', type=float, default=1800)
    parser.add_argument('command', nargs=argparse.REMAINDER)
    args = parser.parse_args()
    command = args.command[1:] if args.command[:1] == ['--'] else args.command
    if not command:
        parser.error('Command is required')
    def interrupted(signum, frame):
        raise SystemExit(128 + signum)
    for signum in (signal.SIGTERM, signal.SIGHUP):
        signal.signal(signum, interrupted)
    args.log.parent.mkdir(parents=True, exist_ok=True)
    sys.exit(run_step(args.label, command, args.log, args.attempts, args.timeout, quiet_stdout=args.quiet_stdout))


if __name__ == '__main__':
    main()
