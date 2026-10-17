import http.client
import json
import unittest
from unittest import mock
from nara import api_keys,clients,rest
from tests import test_api
from tests.helpers import example_state


class RestTests(unittest.TestCase):
    setUp=test_api.APITests.setUp;tearDown=test_api.APITests.tearDown;login=test_api.APITests.login;request=test_api.APITests.request;web_path=''
    def key(self,scopes=None):return api_keys.create(self.store,{'name':'Fixture','days':30,'scopes':scopes or ['read','clients:write','config:write','core:control']})['key']
    def call(self,method,path,body=None,key=None,headers=None):
        connection=http.client.HTTPConnection(*self.server.server_address,timeout=15)
        hdr={'Content-Type':'application/json','Cookie':self.cookie}
        if key:hdr['Authorization']='Bearer '+key
        hdr.update(headers or {})
        connection.request(method,'/api/v1/'+path,json.dumps(body) if body is not None else None,hdr)
        response=connection.getresponse();status=response.status;payload=json.loads(response.read());headers=dict(response.getheaders());connection.close()
        return status,payload,headers
    def seed(self):
        from nara.config import build_config
        self.store.set('state',example_state())
        original=self.runtime.apply.side_effect
        def apply(state,**kwargs):
            build_config(state,self.store.totals(),self.runtime.run_dir,self.runtime.stats_port)
            return original(state,**kwargs)
        self.runtime.apply.side_effect=apply

    def test_bearer_is_required_even_with_a_valid_browser_session(self):
        self.login();self.assertEqual(self.call('GET','status')[0],401)
        key=self.key(['read']);self.assertEqual(self.call('GET','status',key=key)[0],200)
        self.assertEqual(self.call('GET','state',key=key,headers={'Authorization':'Bearer invalid'})[0],401)
        api_keys.revoke(self.store,api_keys.listing(self.store)[0]['id'])
        self.assertEqual(self.call('GET','status',key=key)[0],401)

    def test_secrets_are_hidden_unless_explicitly_permitted(self):
        self.seed();read=self.key(['read']);full=self.key(['read','secrets:read'])
        status,value,_=self.call('GET','clients',key=read);self.assertEqual(status,200);self.assertNotIn('password',value['data'][0]);self.assertNotIn('token',value['data'][0]);self.assertNotIn('uuid',value['data'][0])
        value=self.call('GET','clients',key=full)[1];self.assertIn('password',value['data'][0]);self.assertIn('token',value['data'][0])
        self.assertEqual(self.call('GET','core/config',key=read)[0],403)
        self.assertEqual(self.call('GET','core/config',key=full)[0],200)
        value=rest.visible({'tls':{'private_key':'SECRET'},'headers':{'arbitrary':'SECRET'},'public_key':'PUBLIC','x':{'api_token':'SECRET'}})
        self.assertNotIn('SECRET',json.dumps(value));self.assertEqual(value['public_key'],'PUBLIC')

    def test_scopes_revision_conflicts_and_stale_retries_keep_state(self):
        self.seed();read=self.key(['read']);write=self.key()
        self.assertEqual(self.call('POST','clients',{'revision':0,'inbound_ids':['in1']},read)[0],403)
        self.assertEqual(self.call('POST','clients',{'inbound_ids':['in1']},write)[0],400)
        status,value,headers=self.call('POST','clients',{'inbound_ids':['in1']},write,{'If-Match':'"0"'})
        self.assertEqual(status,201,value);self.assertEqual(value['revision'],1);self.assertEqual(headers['ETag'],'"1"');self.assertRegex(value['data']['name'],r'^[A-Za-z]{10}$')
        after=self.store.get('state');self.assertEqual(self.call('POST','clients',{'revision':0,'inbound_ids':['in1']},write)[0],409)
        self.assertEqual(self.store.get('state'),after)
        self.assertEqual(self.call('PATCH','clients/'+value['data']['id'],{'revision':1,'note':'Updated'},write)[0],200)
        self.assertEqual(self.call('DELETE','clients/'+value['data']['id'],key=write,headers={'If-Match':'2'})[0],200)

    def test_native_crud_and_validation_share_auto_apply(self):
        self.seed();key=self.key();before=self.store.get('state')
        status,value,_=self.call('POST','dns/servers',{'revision':0,'config':{'type':'udp','tag':'google','server':'8.8.8.8','server_port':53}},key)
        self.assertEqual(status,201,value);ident=value['data']['id']
        self.assertEqual(self.call('PATCH','dns/servers/'+ident,{'revision':1,'config':{'server_port':5353}},key)[0],200)
        self.assertEqual(self.store.get('state')['dns_servers'][-1]['config']['server'],'8.8.8.8')
        self.assertEqual(self.call('POST','routing/rules',{'revision':2,'config':{'domain_suffix':['example.com'],'action':'route','outbound':'missing'}},key)[0],400)
        self.assertEqual(self.store.get('state')['revision'],2)
        self.assertEqual(self.call('DELETE','dns/servers/'+ident,{'revision':2},key)[0],200)

    def test_bulk_preview_filters_pagination_and_subscription_scope(self):
        self.seed();key=self.key()
        status,preview,_=self.call('POST','clients/bulk/preview',{'revision':0,'count':3,'pattern':'Team-{n:03}','defaults':{'inbound_ids':['in1'],'tags':['vip']}},key)
        self.assertEqual(status,200,preview)
        status,result,_=self.call('POST','clients/bulk',{'revision':0,'preview_id':preview['preview_id']},key);self.assertEqual(status,200,result)
        status,result,_=self.call('GET','clients?search=Team&tag=vip&limit=2&offset=1',key=key)
        self.assertEqual(status,200);self.assertEqual(len(result['data']),2);self.assertEqual(result['pagination']['total'],3)
        self.assertEqual(self.call('GET','clients/user1/subscription',key=key)[0],403)
        full=self.key(['read','secrets:read']);status,value,_=self.call('GET','clients/user1/subscription',key=full)
        self.assertEqual(status,200,value);self.assertIn(self.store.get('state')['clients'][0]['token'],value['data']['url'])

    def test_rate_limit_expiry_origin_and_schema(self):
        key=self.key(['read']);self.assertEqual(self.call('GET','openapi.json',key=key)[1]['openapi'],'3.1.0')
        self.assertEqual(self.call('GET','schema',key=key)[1]['$schema'],'https://json-schema.org/draft/2020-12/schema')
        self.assertEqual(self.call('POST','core/stop',{'revision':0},key,{'Origin':'https://evil.example'})[0],400)
        with self.store.connect() as db:db.execute('UPDATE api_keys SET expires=0')
        self.assertEqual(self.call('GET','status',key=key)[0],401)
        key=self.key(['read'])
        for _ in range(120):self.assertEqual(self.call('GET','status',key=key)[0],200)
        status,value,headers=self.call('GET','status',key=key);self.assertEqual(status,429);self.assertEqual(headers['Retry-After'],'60')
