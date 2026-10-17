import hashlib
import importlib.util
import io
import json
from pathlib import Path
import struct
import tarfile
import tempfile
import unittest
from unittest import mock

spec=importlib.util.spec_from_file_location('fetch_core',Path(__file__).resolve().parents[1]/'scripts/fetch-core.py')
core=importlib.util.module_from_spec(spec);spec.loader.exec_module(core)


class PrebuiltCoreTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.archive=self.root/'core.tar.gz';self.destination=self.root/'verified'
        self.manifest={'version':'1.14.3','upstream_commit':'a'*40,'release_tag':'core-v1.14.3-nara.1','assets':{'linux-amd64':{'name':'nara-sing-box-1.14.3-linux-amd64.tar.gz','sha256':'0'*64}}}
        header=b'\x7fELF\x02\x01'+b'\0'*12+struct.pack('<H',62)
        self.payload={name:b'upstream notice' for name in core.MEMBERS}
        self.payload.update({'sing-box':header+b'binary','libcronet.so':header+b'library'})
        self.metadata={k:self.manifest[k] for k in ['version','upstream_commit','release_tag']}
        self.metadata.update(os='linux',architecture='amd64',files={name:hashlib.sha256(self.payload[name]).hexdigest() for name in ['sing-box','libcronet.so']})

    def bundle(self, extra=None):
        self.payload['build.json']=json.dumps(self.metadata).encode()
        with tarfile.open(self.archive,'w:gz') as bundle:
            for name,data in self.payload.items():
                entry=tarfile.TarInfo(name);entry.size=len(data);bundle.addfile(entry,io.BytesIO(data))
            if extra:bundle.addfile(extra,io.BytesIO(b'bad') if extra.isfile() else None)
        self.manifest['assets']['linux-amd64']['sha256']=core.digest(self.archive)

    def test_verified_bundle_installs_core_library_and_notices_without_execution(self):
        self.bundle()
        with mock.patch.object(core.subprocess,'run') as execution:
            result=core.unpack(self.archive,self.destination,self.manifest,'amd64')
        execution.assert_not_called()
        self.assertEqual(result,self.destination/'sing-box')
        self.assertEqual(set(p.name for p in self.destination.iterdir()),core.MEMBERS)
        self.assertEqual(result.stat().st_mode&0o777,0o755)
        self.assertEqual((self.destination/'SING-BOX-COPYING').stat().st_mode&0o777,0o644)

    def test_bad_archive_checksum_never_publishes_files(self):
        self.bundle();self.archive.write_bytes(self.archive.read_bytes()+b'corrupt')
        with self.assertRaisesRegex(ValueError,'checksum'):core.unpack(self.archive,self.destination,self.manifest,'amd64')
        self.assertFalse(self.destination.exists())

    def test_traversal_links_duplicates_and_missing_files_are_rejected(self):
        for name,kind in [('../escape',tarfile.REGTYPE),('sing-box',tarfile.SYMTYPE),('sing-box',tarfile.REGTYPE)]:
            with self.subTest(name=name,kind=kind):
                extra=tarfile.TarInfo(name);extra.type=kind;extra.size=3 if kind==tarfile.REGTYPE else 0;extra.linkname='/etc/passwd'
                self.bundle(extra)
                with self.assertRaisesRegex(ValueError,'unsafe'):core.unpack(self.archive,self.destination,self.manifest,'amd64')
                self.assertFalse(self.destination.exists())
        del self.payload['libcronet.so'];self.bundle()
        with self.assertRaisesRegex(ValueError,'incomplete'):core.unpack(self.archive,self.destination,self.manifest,'amd64')

    def test_metadata_and_payload_architecture_must_match_the_manifest(self):
        for key,value in [('version','9.0.0'),('architecture','arm64'),('upstream_commit','b'*40)]:
            old=self.metadata[key];self.metadata[key]=value;self.bundle()
            with self.assertRaisesRegex(ValueError,'metadata'):core.unpack(self.archive,self.destination,self.manifest,'amd64')
            self.metadata[key]=old
        self.payload['sing-box']=b'wrong ELF';self.metadata['files']['sing-box']=hashlib.sha256(b'wrong ELF').hexdigest();self.bundle()
        with self.assertRaisesRegex(ValueError,'ELF'):core.unpack(self.archive,self.destination,self.manifest,'amd64')

    def test_library_payload_has_its_own_checksum(self):
        self.metadata['files']['libcronet.so']='0'*64;self.bundle()
        with self.assertRaisesRegex(ValueError,'payload checksum'):core.unpack(self.archive,self.destination,self.manifest,'amd64')

    def test_existing_destination_is_not_replaced(self):
        self.bundle();self.destination.mkdir();(self.destination/'keep').write_text('existing core')
        with self.assertRaisesRegex(ValueError,'already exists'):core.unpack(self.archive,self.destination,self.manifest,'amd64')
        self.assertEqual((self.destination/'keep').read_text(),'existing core')

    def test_download_is_fixed_https_and_has_no_build_fallback(self):
        self.bundle()
        def download(command,**kwargs):
            self.assertEqual(command[0],'curl');self.assertIn('--retry-all-errors',command)
            url=next(v for v in command if v.startswith('https://'))
            self.assertTrue(url.startswith(core.REPOSITORY+'/releases/download/core-v1.14.3-nara.1/'))
            Path(command[-1]).write_bytes(self.archive.read_bytes())
        with mock.patch.object(core.subprocess,'run',side_effect=download) as run:
            core.fetch(self.manifest,'amd64',self.destination)
        self.assertEqual(run.call_count,1)

    def test_host_architectures_and_untrusted_artifact_fields(self):
        self.assertEqual(core.architecture('aarch64'),'arm64');self.assertEqual(core.architecture('x86_64'),'amd64')
        with self.assertRaises(ValueError):core.architecture('i686')
        self.manifest['assets']['linux-amd64']['name']='../escape'
        with self.assertRaises(ValueError):core.artifact(self.manifest,'amd64')


class NoCompilerInstallerTests(unittest.TestCase):
    def test_download_failure_keeps_existing_installation_running_and_never_calls_go(self):
        import os
        import subprocess
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);source=root/'source';fakebin=root/'fakebin'
            (source/'scripts').mkdir(parents=True);fakebin.mkdir()
            (source/'scripts/terminal.sh').write_text(Path('scripts/terminal.sh').read_text())
            app=root/'opt/nara-panel';app.mkdir(parents=True);(app/'keep').write_text('working installation')
            calls=root/'commands.log'
            scripts={'uname':'echo Linux','id':'echo 0','systemctl':'echo "$*" >> "$NARA_TEST_CALLS"; exit 1','python3':'case "$1" in -c) exit 0 ;; *) echo download-failed >&2; exit 47 ;; esac','go':'echo GO-MUST-NOT-RUN >> "$NARA_TEST_CALLS"; exit 99','git':'echo GIT-MUST-NOT-RUN >> "$NARA_TEST_CALLS"; exit 99'}
            for name,body in scripts.items():
                path=fakebin/name;path.write_text('#!/bin/sh\n'+body+'\n');path.chmod(0o755)
            script=Path('scripts/install.sh').read_text()
            for path in ['/opt/nara-panel','/etc/nara-panel.env','/etc/systemd/system','/usr/local/bin/nara','/var/lib/nara-panel','/etc/nara-panel/https']:
                script=script.replace(path,str(root)+path)
            target=source/'scripts/install.sh';target.write_text(script)
            environment={**os.environ,'PATH':str(fakebin)+':'+os.environ['PATH'],'NARA_MANAGER_LOCK_HELD':'1','NARA_TEST_CALLS':str(calls)}
            environment.pop('NARA_INSTALL_CORE',None)
            result=subprocess.run(['sh',str(target)],env=environment,capture_output=True,text=True)
            self.assertEqual(result.returncode,47,result.stdout+result.stderr)
            self.assertEqual((app/'keep').read_text(),'working installation')
            log=calls.read_text();self.assertNotIn('stop ',log);self.assertNotIn('MUST-NOT-RUN',log)

    def test_manager_prepares_runtime_dependencies_without_go_or_git(self):
        import subprocess,sys,shlex
        result=subprocess.run(['bash','-c','python3() { '+shlex.quote(sys.executable)+' "$@"; }\nsource scripts/manage.sh\napt-get() { printf "APT %s\\n" "$*"; }\nprepare_install'],capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertIn('python3-venv openssl',result.stdout)
        self.assertNotIn('golang',result.stdout);self.assertNotIn(' git',result.stdout)


class DiagnosticPrivacyTests(unittest.TestCase):
    def test_ci_diagnostics_contain_only_fixed_categories_and_integer_counts(self):
        from tests.test_core import diagnostic_categories
        secret='private-password-value-should-never-be-printed'
        categories=diagnostic_categories('ERROR DNS connection refused password='+secret+' uuid=private-user-id')
        self.assertEqual(categories,{'connection refused':1,'dns':1,'error':1})
        self.assertNotIn(secret,json.dumps(categories))
        self.assertTrue(all(type(value) is int for value in categories.values()))


class CorePackageTests(unittest.TestCase):
    def test_release_bundle_has_exact_notices_metadata_and_matching_payload_hashes(self):
        import subprocess
        spec=importlib.util.spec_from_file_location('package_core',Path(__file__).resolve().parents[1]/'scripts/package-core.py')
        package=importlib.util.module_from_spec(spec);spec.loader.exec_module(package)
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);(root/'deploy/licenses').mkdir(parents=True)
            config={'version':'1.14.3','upstream_commit':'a'*40,'release_tag':'core-v1.14.3-nara.1'}
            (root/'core-build.json').write_text(json.dumps(config));(root/'deploy/licenses/GPL-3.0.txt').write_text('GPL text')
            source=root/'upstream';source.mkdir();(source/'LICENSE').write_text('Original upstream notice')
            binary=root/'sing-box';binary.write_bytes(b'core payload');(root/'libcronet.so').write_bytes(b'library payload');(root/'libcronet.LICENSE').write_text('Cronet notice')
            with mock.patch.object(package.subprocess,'check_output',side_effect=['b'*40,'a'*40,'sing-box version 1.14.3\nTags: with_v2ray_api,with_quic\n']):
                package.package(root,binary,'amd64',root/'release',source)
            archive=root/'release/nara-sing-box-1.14.3-linux-amd64.tar.gz'
            with tarfile.open(archive) as bundle:
                self.assertEqual(set(bundle.getnames()),core.MEMBERS)
                metadata=json.load(bundle.extractfile('build.json'))
                self.assertEqual(metadata['files']['sing-box'],hashlib.sha256(b'core payload').hexdigest())
                self.assertEqual(bundle.extractfile('SING-BOX-LICENSE').read(),b'Original upstream notice')
            self.assertTrue((archive.parent/(archive.name+'.sha256')).read_text().startswith(core.digest(archive)))
