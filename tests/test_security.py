import base64
import hashlib
import io
import json
import struct
import tempfile
import time
import unittest
import zlib
from unittest import mock
from nara import security,api_keys,accounts
from nara.store import Store,password_hash
from tests import test_api


def png(width=2,height=2,extra=b''):
    def chunk(kind,value):return struct.pack('!I',len(value))+kind+value+struct.pack('!I',zlib.crc32(kind+value)&0xffffffff)
    raw=b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('!IIBBBBB',width,height,8,6,0,0,0))+extra+chunk(b'IDAT',zlib.compress((b'\x00'+b'\xff\0\0\xff'*width)*height))+chunk(b'IEND',b'')
    return 'data:image/png;base64,'+base64.b64encode(raw).decode()


class SecurityTests(unittest.TestCase):
    def test_totp_rfc6238_vectors_and_replay_window(self):
        secret=base64.b32encode(b'12345678901234567890').decode()
        for stamp,expected in [(59,'94287082'),(1111111109,'07081804'),(1111111111,'14050471'),(1234567890,'89005924'),(2000000000,'69279037'),(20000000000,'65353130')]:
            self.assertEqual(security.totp(secret,stamp//30,8),expected)
        code=security.totp(secret,100)
        self.assertEqual(security.totp_counter(secret,code,now=3000),100)
        self.assertIsNone(security.totp_counter(secret,code,last=100,now=3000))
        self.assertIsNone(security.totp_counter(secret,code,now=3061))

    def test_recovery_codes_are_hashed_and_one_use(self):
        codes,hashes=security.recovery_codes();admin={'totp_secret':security.totp_secret(),'recovery_hashes':hashes}
        self.assertEqual(len(set(codes)),10)
        self.assertTrue(security.verify_factor(admin,codes[0].lower()))
        self.assertFalse(security.verify_factor(admin,codes[0]))
        self.assertEqual(len(admin['recovery_hashes']),9)
        self.assertNotIn(codes[1],json.dumps(security.public_admin({'username':'admin',**admin})))

    def test_avatar_normalizes_png_and_rejects_unsafe_or_oversized_images(self):
        self.assertEqual(security.validate_avatar('ocean'),'ocean')
        self.assertEqual(security.validate_avatar(png()),png())
        for value in ['https://example.com/avatar.jpg','data:image/svg+xml;base64,PHN2Zz4=',png(513,1),png()+'junk','data:image/png;base64,'+base64.b64encode(b'not PNG').decode()]:
            with self.subTest(value=value[:32]),self.assertRaises(ValueError):security.validate_avatar(value)
        raw=base64.b64decode(png().split(',',1)[1]);corrupt=raw[:40]+bytes([raw[40]^1])+raw[41:]
        with self.assertRaises(ValueError):security.validate_avatar('data:image/png;base64,'+base64.b64encode(corrupt).decode())


class AccountAPITests(unittest.TestCase):
    setUp=test_api.APITests.setUp;tearDown=test_api.APITests.tearDown;request=test_api.APITests.request;login=test_api.APITests.login;web_path=''

    def test_credentials_require_current_password_and_revoke_all_sessions(self):
        self.login();body={'username':'NewOwner','password':'new-password-123','current':'wrong'}
        self.assertEqual(self.request('/api/admin/credentials',body)[0],400)
        body['current']='test-password-123';body['password_confirm']='new-password-123'
        self.assertEqual(self.request('/api/admin/credentials',body)[0],200)
        self.assertEqual(self.request('/api/state')[0],401)
        result=self.request('/api/login',{'username':'NewOwner','password':'new-password-123'})
        self.assertEqual(result[0],200)

    def test_totp_setup_confirmation_login_replay_and_recovery(self):
        self.login();body={'current':'test-password-123'}
        status,setup,_=self.request('/api/admin/2fa/setup',body);self.assertEqual(status,200,setup)
        self.assertIn('otpauth://totp/',setup['uri'])
        counter=int(time.time()//30)
        with mock.patch('nara.security.time.time',return_value=counter*30):
            code=security.totp(setup['secret'],counter)
            status,result,_=self.request('/api/admin/2fa/enable',{**body,'totp_code':code})
            self.assertEqual(status,200,result);codes=result['recovery_codes']
            public=json.dumps(self.request('/api/admin')[1])+json.dumps(self.request('/api/session')[1])
            self.assertNotIn(setup['secret'],public);self.assertNotIn(codes[0],public)
            self.assertNotIn(codes[0],json.dumps(self.store.get('admin')))
            self.request('/api/logout',{})
            status,result,headers=self.request('/api/login',{'username':'admin','password':body['current']})
            self.assertEqual(status,200);self.assertTrue(result['two_factor_required']);self.assertNotIn('Set-Cookie',headers)
            self.assertEqual(self.request('/api/login',{'username':'admin','password':body['current'],'code':code})[0],401)
            self.assertEqual(self.request('/api/login',{'username':'admin','password':body['current'],'code':codes[0]})[0],200)
            self.assertEqual(self.request('/api/login',{'username':'admin','password':body['current'],'code':codes[0]})[0],401)
            next_code=security.totp(setup['secret'],counter+1)
            self.assertEqual(self.request('/api/login',{'username':'admin','password':body['current'],'code':next_code})[0],200)

    def test_pending_totp_is_session_bound_and_expires(self):
        self.login();self.request('/api/admin/2fa/setup',{'current':'test-password-123'})
        pending=self.store.get('admin')['totp_pending'];secret=pending['secret']
        token,csrf=self.store.new_session();self.cookie='nara_session='+token;self.csrf=csrf
        self.assertEqual(self.request('/api/admin/2fa/enable',{'current':'test-password-123','totp_code':security.totp(secret,int(time.time()//30))})[0],400)
        self.assertFalse(self.store.get('admin').get('totp_secret'))

    def test_avatar_and_api_keys_remain_private_and_revocable(self):
        self.login();self.assertEqual(self.request('/api/admin/avatar',{'avatar':png()})[0],200)
        self.assertEqual(self.request('/api/session')[1]['avatar'],png())
        status,value,_=self.request('/api/api-keys/create',{'current':'test-password-123','name':'Automation','days':30,'scopes':['read','clients:write']})
        self.assertEqual(status,200,value);key=value['key']
        self.assertNotIn(key,json.dumps(self.request('/api/api-keys')[1]))
        with self.store.connect() as db:self.assertNotIn(key,str(db.execute('SELECT * FROM api_keys').fetchall()))
        self.assertIsNotNone(api_keys.authenticate(self.store,'Bearer '+key))
        self.assertEqual(self.request('/api/api-keys/revoke',{'current':'test-password-123','id':value['id']})[0],200)
        self.assertIsNone(api_keys.authenticate(self.store,'Bearer '+key))
