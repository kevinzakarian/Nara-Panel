"""Exercise the build runner with real subprocesses and controlled failures."""
import contextlib
import importlib.util
import io
import os
import time
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

spec = importlib.util.spec_from_file_location('build_step',Path(__file__).resolve().parents[1]/'scripts/build-step.py')
build = importlib.util.module_from_spec(spec);spec.loader.exec_module(build)


class BuildDownloadTests(unittest.TestCase):
    def invoke(self, script, attempts=3, timeout=5, quiet=False):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            code = "from pathlib import Path\nimport sys,time\np=Path("+repr(str(root/'attempt'))+")\nn=int(p.read_text())+1 if p.exists() else 1\np.write_text(str(n))\n"+script
            output = io.StringIO()
            with contextlib.redirect_stdout(output),contextlib.redirect_stderr(output):
                status = build.run_step('Fixture download',[sys.executable,'-c',code],root/'build.log',attempts=attempts,timeout=timeout,delay=0,quiet_stdout=quiet)
            return status, int((root/'attempt').read_text()), output.getvalue(), (root/'build.log').read_text()

    def test_network_error_retries_and_keeps_diagnostics_until_success(self):
        status,count,output,log = self.invoke("print('dial tcp: i/o timeout' if n<3 else 'ready',file=sys.stderr)\nsys.exit(1 if n<3 else 0)")
        self.assertEqual((status,count),(0,3))
        self.assertIn('retrying',output)
        self.assertIn('i/o timeout',log)
        self.assertIn('ready',log)

    def test_checksum_or_compile_failure_does_not_retry(self):
        for error in ['checksum mismatch SECURITY ERROR','compile: undefined: missing','compile: signal: killed']:
            with self.subTest(error=error):
                status,count,output,log = self.invoke('print('+repr(error)+',file=sys.stderr)\nsys.exit(1)')
                self.assertEqual((status,count),(1,1))
                self.assertIn(error,log)
                if 'killed' in error:self.assertIn('RAM',output)

    def test_checksum_failure_is_never_retried_even_with_network_words(self):
        status,count,_,_ = self.invoke("print('checksum mismatch after timeout',file=sys.stderr)\nsys.exit(1)")
        self.assertEqual((status,count),(1,1))

    def test_hanging_download_is_killed_and_attempts_are_bounded(self):
        status,count,output,_ = self.invoke('time.sleep(10)',attempts=2,timeout=.25)
        self.assertEqual((status,count),(1,2))
        self.assertIn('time limit',output)

    def test_package_stdout_is_hidden_but_download_stderr_is_logged(self):
        status,_,output,log = self.invoke("print('package/listing');print('go: downloading module',file=sys.stderr)",quiet=True)
        self.assertEqual(status,0)
        self.assertNotIn('package/listing',output+log)
        self.assertIn('go: downloading module',output+log)

    def test_interrupt_stops_the_owned_build_subprocess(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); pid_path=root/'child.pid'
            command=[sys.executable,str(Path(build.__file__)), '--label','Interrupt fixture','--log',str(root/'log'),'--',sys.executable,'-c',"import os,time;from pathlib import Path;Path("+repr(str(pid_path))+").write_text(str(os.getpid()));time.sleep(20)"]
            process=subprocess.Popen(command,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True)
            child=None
            try:
                deadline=time.monotonic()+5
                while not pid_path.exists() and time.monotonic()<deadline:time.sleep(.01)
                self.assertTrue(pid_path.exists())
                child=int(pid_path.read_text())
                process.terminate();process.communicate(timeout=5)
                self.assertEqual(process.returncode,143)
                with self.assertRaises(ProcessLookupError):os.kill(child,0)
            finally:
                if process.poll() is None:process.kill();process.communicate()
                if child:
                    try:os.kill(child,9)
                    except ProcessLookupError:pass
