const assert=require('node:assert/strict');
const {test}=require('node:test');
const fs=require('node:fs');
const vm=require('node:vm');
const context=vm.createContext({});vm.runInContext(fs.readFileSync('web/dns-presets.js','utf8')+'\nglobalThis.presets=DNSPresets;',context);
const p=context.presets,plain=value=>JSON.parse(JSON.stringify(value));
test('every preset protocol creates a self-contained endpoint with verified TLS names and reversible detection',()=>{
 let count=0;
 for(const [provider,info] of Object.entries(p.providers))for(const type of info.types){
  const c=plain(p.build(provider,type,'abc123'));
  assert.equal(c.type,type);assert.ok(c.server);assert.ok(c.server_port>0);assert.ok(!Object.hasOwn(c,'domain_resolver'));
  if(['tls','https','quic'].includes(type)){assert.equal(c.tls.enabled,true);assert.ok(c.tls.server_name);assert.ok(!c.tls.insecure);}else assert.ok(!Object.hasOwn(c,'tls'));
  assert.deepEqual(plain(p.detect(c)),{provider,profileId:provider==='nextdns'?'abc123':''});count++;
 }
 assert.equal(count,23);
 assert.equal(p.build('opendns','https').server,'146.112.41.2');
 assert.equal(p.build('cloudflare','tls').tls.server_name,'one.one.one.one');
 assert.throws(()=>p.build('google','quic'),/supported/);
});
test('custom settings are not silently recognized as provider templates and NextDNS IDs are validated',()=>{
 assert.equal(p.detect({type:'https',server:'192.0.2.1'}).provider,'custom');
 for(const id of ['','abc','../bad','abcdefg'])assert.throws(()=>p.validate('nextdns',id),/Profile ID/);
 p.validate('nextdns',' AB12CD ');
 const result=plain(p.apply('nextdns',{type:'https',tag:'private',server_port:8443,tls:{certificate:['DEMO CA'],insecure:false}},'abc123'));
 assert.equal(result.server_port,8443);assert.equal(result.tag,'private');assert.deepEqual(result.tls.certificate,['DEMO CA']);assert.equal(result.tls.insecure,false);
});
