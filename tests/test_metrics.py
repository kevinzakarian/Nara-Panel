import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest import mock
from nara import runtime as r


class HardwareMetricsTests(unittest.TestCase):
    def test_x86_and_arm_cpu_models_do_not_return_a_processor_index(self):
        for source, expected in [('processor : 0\nmodel name : AMD EPYC 7B13 64-Core Processor\n', 'AMD EPYC 7B13 64-Core Processor'),
                                 ('processor : 0\nProcessor : ARMv8 Processor rev 1\nHardware : Board\n', 'ARMv8 Processor rev 1')]:
            with mock.patch.object(Path, 'read_text', return_value=source):
                self.assertEqual(r.cpu_model(), expected)
        with mock.patch.object(Path, 'read_text', side_effect=OSError), mock.patch.object(r.os, 'uname', return_value=mock.Mock(sysname='Linux')):
            self.assertIsNone(r.cpu_model())

    def test_arm_cpu_without_a_brand_string_uses_lscpu_model(self):
        result=subprocess.CompletedProcess([],0,json.dumps({'lscpu':[{'field':'Model name:','data':'Neoverse-N1'}]}))
        with mock.patch.object(Path,'read_text',return_value='processor : 0\nCPU implementer : 0x41\n'),mock.patch.object(r.os,'uname',return_value=mock.Mock(sysname='Linux')),mock.patch.object(r.subprocess,'run',return_value=result):
            self.assertEqual(r.cpu_model(),'Neoverse-N1')

    def test_network_addresses_filter_local_invalid_states_and_deduplicate(self):
        interfaces = [{'ifname':'lo','addr_info':[{'local':'127.0.0.1'},{'local':'::1'}]},
                      {'ifname':'eth0','addr_info':[{'local':'10.0.0.5'},{'local':'8.8.8.8'},{'local':'8.8.8.8'},
                       {'local':'2001:4860:4860::8888'}, {'local':'fd00::1'}, {'local':'fe80::1'},
                       {'local':'169.254.1.1'}, {'local':'0.0.0.0'}, {'local':'ff02::1'},
                       {'local':'2001:db8::1','flags':['tentative']}, {'local':'2001:db8::2','preferred_life_time':0}]}]
        with mock.patch.object(r.subprocess, 'run', return_value=subprocess.CompletedProcess([],0,json.dumps(interfaces))) as run:
            ipv4, ipv6 = r.interface_addresses()
        self.assertEqual(ipv4,['8.8.8.8','10.0.0.5'])
        self.assertEqual(ipv6,['2001:4860:4860::8888','fd00::1'])
        self.assertEqual(run.call_args.args[0],['ip','-j','address','show','up'])
        self.assertEqual(run.call_args.kwargs['timeout'],2)

    def test_missing_ipv6_is_distinct_from_discovery_failure(self):
        with mock.patch.object(r.subprocess,'run',return_value=subprocess.CompletedProcess([],0,'[]')):
            self.assertEqual(r.interface_addresses(),([],[]))
        for problem in [FileNotFoundError(),subprocess.TimeoutExpired('ip',2)]:
            with mock.patch.object(r.subprocess,'run',side_effect=problem):
                self.assertEqual(r.interface_addresses(),(None,None))
        with mock.patch.object(r.subprocess,'run',return_value=subprocess.CompletedProcess([],0,'not json')):
            self.assertEqual(r.interface_addresses(),(None,None))

    def test_existing_minimal_linux_can_fall_back_without_iproute2(self):
        with mock.patch.object(r.os,'uname',return_value=mock.Mock(sysname='Linux')), mock.patch.object(r.subprocess,'run',side_effect=[FileNotFoundError(),subprocess.CompletedProcess([],0,'10.0.0.1 2001:db8::1 fe80::1')]):
            self.assertEqual(r.interface_addresses(),(['10.0.0.1'],['2001:db8::1']))

    def test_hardware_cache_refreshes_without_breaking_existing_metrics(self):
        metrics = r.Metrics()
        with tempfile.TemporaryDirectory() as directory, mock.patch.object(r,'cpu_model',return_value='Test CPU') as cpu, mock.patch.object(r,'interface_addresses',return_value=(['203.0.113.1'],[])) as address, mock.patch.object(r.time,'monotonic',side_effect=[0,5,61]):
            for _ in range(3):
                data = metrics.read(directory)
                self.assertEqual(data['cpu_model'],'Test CPU')
                self.assertEqual(data['ipv4'],['203.0.113.1'])
                self.assertIn('disk_total',data)
        self.assertEqual(cpu.call_count,2)
        self.assertEqual(address.call_count,2)
