import copy
import datetime as dt
import json
import re
import unittest
from nara import clients
from nara.config import validate
from tests import test_api
from tests.helpers import example_state


class NamingTests(unittest.TestCase):
    def test_random_names_are_ten_unique_mixed_case_letters(self):
        used=set()
        for _ in range(1000):
            name=clients.random_name(used);self.assertRegex(name,r'^[A-Za-z]{10}$');self.assertRegex(name,r'[A-Z]');self.assertRegex(name,r'[a-z]');self.assertNotIn(name,used);used.add(name)

    def test_bulk_patterns_and_unsafe_or_duplicate_tokens(self):
        state=example_state();state['client_groups']=[{'id':'team','name':'Team'}]
        data={'count':3,'pattern':'{group}-{n:03}-{random}','start':8,'defaults':{'inbound_ids':['in1'],'group_ids':['team']}}
        rows=clients.plan_create(state,data)
        for index,row in enumerate(rows):self.assertRegex(row['name'],r'^Team-0'+str(8+index).zfill(2)+r'-[A-Za-z]{10}$')
        for pattern in ['same-name','{unknown}','{n.__class__}','{n:999999999999}','{random','test}']:
            with self.subTest(pattern=pattern),self.assertRaises(ValueError):clients.plan_create(state,{**data,'pattern':pattern})
        self.assertEqual(len(state['clients']),1)


class BulkAPITests(unittest.TestCase):
    setUp=test_api.APITests.setUp;tearDown=test_api.APITests.tearDown;request=test_api.APITests.request;login=test_api.APITests.login;web_path=''
    def seed(self):
        self.login();state=example_state();state['client_groups']=[{'id':'team','name':'Team','description':''}];self.store.set('state',state);return state

    def test_preview_names_are_stable_and_creates_apply_once(self):
        before=self.seed();data={'revision':0,'count':4,'defaults':{'inbound_ids':['in1'],'group_ids':['team'],'quota_bytes':1000},'pattern':''}
        status,preview,_=self.request('/api/clients-bulk-preview',data);self.assertEqual(status,200,preview)
        self.assertEqual(self.store.get('state'),before);self.runtime.apply.assert_not_called()
        status,result,_=self.request('/api/clients-bulk-create',{'revision':0,'preview_id':preview['preview_id']})
        self.assertEqual(status,200,result);self.assertEqual(len(result['ids']),4);self.assertEqual(self.runtime.apply.call_count,1)
        after=self.store.get('state');self.assertEqual([r['name'] for r in after['clients'][1:]],[r['name'] for r in preview['examples']])
        self.assertEqual(len({r['uuid'] for r in after['clients']}),5);self.assertEqual(len({r['token'] for r in after['clients']}),5)
        self.assertEqual(self.request('/api/clients-bulk-create',{'revision':0,'preview_id':preview['preview_id']})[0],400)
        self.assertEqual(self.store.get('state'),after)

    def test_duplicate_pattern_or_bad_assignment_never_changes_settings(self):
        before=self.seed()
        for extra in [{'pattern':'same'},{'defaults':{'inbound_ids':['missing']}},{'defaults':{'inbound_ids':['in1'],'group_ids':['missing']}}]:
            body={'revision':0,'count':3,'defaults':{'inbound_ids':['in1']},**extra}
            self.assertEqual(self.request('/api/clients-bulk-create',body)[0],400)
            self.assertEqual(self.store.get('state'),before)
        self.runtime.apply.assert_not_called()

    def test_bulk_actions_preserve_unlimited_accounts_and_can_detach_groups(self):
        state=self.seed();first=state['clients'][0];first.update(quota_bytes=1000,group_ids=['team'],tags=['paid'],expires_at='2030-01-01T00:00:00+00:00')
        other=clients.new_client({'name':'Unlimited','inbound_ids':['in1']});state['clients'].append(other);self.store.set('state',state)
        for operation,value in [('quota_subtract',1000),('groups_set',[]),('tags_set',['vip']),('expiry_extend',5)]:
            revision=self.store.get('state')['revision']
            status,result,_=self.request('/api/clients-bulk-action',{'revision':revision,'ids':[first['id'],other['id']],'operation':operation,'value':value})
            self.assertEqual(status,200,result)
        after=self.store.get('state');self.assertEqual(after['clients'][0]['quota_bytes'],1);self.assertEqual(after['clients'][1]['quota_bytes'],0)
        self.assertEqual(after['clients'][0]['group_ids'],[]);self.assertEqual(after['clients'][1]['tags'],['vip'])
        self.assertTrue(after['clients'][0]['expires_at'].startswith('2030-01-06'));self.assertFalse(after['clients'][1]['expires_at'])

    def test_reset_and_delete_are_atomic_and_unsupported_values_roll_back(self):
        before=self.seed();other=clients.new_client({'name':'Other','inbound_ids':['in1']});before['clients'].append(other);self.store.set('state',before)
        ids=[r['id'] for r in before['clients']]
        for ident in ids:self.store.add_traffic([(ident,'upload',50)])
        status,result,_=self.request('/api/clients-bulk-action',{'revision':0,'ids':ids,'operation':'reset_traffic'})
        self.assertEqual(status,200,result);self.assertEqual(self.store.totals(),{})
        current=self.store.get('state')
        self.assertEqual(self.request('/api/clients-bulk-action',{'revision':current['revision'],'ids':ids,'operation':'inbounds_set','value':[]})[0],400)
        self.assertEqual(self.store.get('state'),current)
        self.assertEqual(self.request('/api/clients-bulk-action',{'revision':current['revision'],'ids':ids,'operation':'delete'})[0],200)
        self.assertEqual(self.store.get('state')['clients'],[])

    def test_failed_apply_keeps_entire_batch_and_traffic_unchanged(self):
        from unittest import mock
        before=self.seed();self.store.add_traffic([('user1','download',500)])
        with mock.patch.object(self.runtime,'apply',side_effect=ValueError('Core rejected batch')):
            self.assertEqual(self.request('/api/clients-bulk-action',{'revision':0,'ids':['user1'],'operation':'reset_traffic'})[0],400)
        self.assertEqual(self.store.get('state'),before);self.assertEqual(self.store.totals()['user1']['download'],500)

    def test_group_deletion_detaches_members_without_deleting_clients(self):
        state=self.seed();state['clients'][0]['group_ids']=['team'];self.store.set('state',state)
        self.assertEqual(self.request('/api/delete',{'revision':0,'collection':'client_groups','id':'team'})[0],200)
        after=self.store.get('state');self.assertEqual(len(after['clients']),1);self.assertEqual(after['clients'][0]['group_ids'],[])

    def test_preview_cannot_be_used_from_another_session(self):
        self.seed();_,preview,_=self.request('/api/clients-bulk-preview',{'revision':0,'count':1,'defaults':{'inbound_ids':['in1']}})
        token,self.csrf=self.store.new_session();self.cookie='nara_session='+token
        self.assertEqual(self.request('/api/clients-bulk-create',{'revision':0,'preview_id':preview['preview_id']})[0],400)
        self.assertEqual(len(self.store.get('state')['clients']),1)
