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
 assert.equal(count,39);
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
test('resolver addresses follow protocol, path, TLS name and custom ports without changing core Server',()=>{
 const c=plain(p.build('google','https'));
 assert.deepEqual(plain(p.endpoint(c)),{url:'https://dns.google/dns-query',address:'8.8.8.8:443'});assert.equal(c.server,'8.8.8.8');
 assert.equal(p.endpoint(p.build('cloudflare','tls')).url,'tls://one.one.one.one:853');
 assert.equal(p.endpoint(p.build('nextdns','quic','abc123')).url,'quic://abc123.dns.nextdns.io:853');
 assert.equal(p.endpoint(p.build('quad9','udp')).url,'udp://9.9.9.9:53');
 assert.deepEqual(plain(p.endpoint({type:'h3',server:'2001:db8::1',server_port:8443,path:'/custom'})),{url:'https://[2001:db8::1]:8443/custom',address:'[2001:db8::1]:8443'});
 assert.equal(p.endpoint({type:'local',tag:'local'}),null);assert.equal(p.endpoint({type:'https',server:'https://dns.google/dns-query'}),null);
});

test('family presets use filtered endpoints and CleanBrowsing keeps its own HTTPS path and TLS name',()=>{
 for(const [provider,ip,sni] of [['adguard-family','94.140.14.15','family.adguard-dns.com'],['cloudflare-family','1.1.1.3','family.cloudflare-dns.com']]){
  const c=p.build(provider,'https');assert.equal(c.server,ip);assert.equal(c.tls.server_name,sni);assert.equal(c.path,'/dns-query');
 }
 const clean=p.build('cleanbrowsing-family','https');assert.equal(clean.server,'185.228.168.168');assert.equal(clean.tls.server_name,'doh.cleanbrowsing.org');assert.equal(clean.path,'/doh/family-filter/');assert.equal(p.build('cleanbrowsing-family','tls').tls.server_name,'family-filter-dns.cleanbrowsing.org');
 const open=p.build('opendns-family','https');assert.equal(open.server,'146.112.41.3');assert.equal(open.tls.server_name,'doh.familyshield.opendns.com');assert.equal(p.build('opendns-family','udp').server,'208.67.222.123');
 assert.throws(()=>p.build('cloudflare-family','quic'),/supported/);
});
