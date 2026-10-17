'use strict';
// Addresses and encrypted transport names come from the providers' public docs.
const DNSPresets=(()=>{
 const ports={udp:53,tcp:53,tls:853,https:443,quic:853};
 const providers={
  google:{name:'Google Public DNS',server:'8.8.8.8',sni:'dns.google',types:['udp','tcp','tls','https'],note:'Public resolver without ad blocking.'},
  cloudflare:{name:'Cloudflare',server:'1.1.1.1',sni:'cloudflare-dns.com',types:['udp','tcp','tls','https'],note:'Standard unfiltered 1.1.1.1 resolver.'},
  quad9:{name:'Quad9',server:'9.9.9.9',sni:'dns.quad9.net',types:['udp','tcp','tls','https'],note:'Secure service with malicious-domain blocking.'},
  adguard:{name:'AdGuard DNS',server:'94.140.14.14',sni:'dns.adguard-dns.com',types:['udp','tcp','tls','https','quic'],note:'Default service blocks advertising and tracking domains.'},
  opendns:{name:'OpenDNS',server:'208.67.222.222',sni:'doh.opendns.com',types:['udp','tcp','https'],note:'Standard OpenDNS service; HTTPS uses its dedicated endpoint.'},
  nextdns:{name:'NextDNS',server:'45.90.28.0',sni:'dns.nextdns.io',types:['tls','https','quic'],note:'Uses your personal NextDNS profile. Enter its six-character Profile ID.'}
 };
 function build(provider,type,profileId='',tag=''){
  const p=providers[provider];if(!p||!p.types.includes(type))throw new Error('Choose a supported provider and protocol.');
  const profile=profileId.trim().toLowerCase();
  const c={type,tag:tag||'dns-'+provider,server:provider==='opendns'&&type==='https'?'146.112.41.2':p.server,server_port:ports[type]};
  if(['tls','https','quic'].includes(type))c.tls={enabled:true,server_name:provider==='cloudflare'&&type==='tls'?'one.one.one.one':provider==='nextdns'&&type!=='https'&&profile?profile+'.dns.nextdns.io':p.sni};
  if(type==='https')c.path=provider==='nextdns'?'/'+profile:'/dns-query';
  return c;
 }
 function detect(config){
  for(const [provider,p] of Object.entries(providers)){
   if(!p.types.includes(config.type))continue;
   const profileId=provider==='nextdns'?(config.type==='https'?/^\/([a-f0-9]{6})\/?$/i.exec(config.path||'')?.[1]:/^([a-f0-9]{6})\.dns\.nextdns\.io$/i.exec(config.tls?.server_name||'')?.[1])||'':'';
   if(provider==='nextdns'&&!profileId)continue;
   const c=build(provider,config.type,profileId);
   if(c.server!==config.server||(c.tls&&c.tls.server_name!==config.tls?.server_name)||(c.path&&(config.path||'/dns-query')!==c.path))continue;
   return {provider,profileId};
  }
  return {provider:'custom',profileId:''};
 }
 function apply(provider,config,profileId=''){
  const generated=build(provider,config.type,profileId,config.tag);
  return {...config,...generated,tag:config.tag,server_port:config.server_port??generated.server_port,...(generated.tls?{tls:{...config.tls,...generated.tls}}:{})};
 }
 function validate(provider,profileId){if(provider==='nextdns'&&!/^[a-f0-9]{6}$/i.test(profileId.trim()))throw new Error('Enter the six-character NextDNS Profile ID from your NextDNS dashboard.');}
 function endpoint(config){
  if(!['udp','tcp','tls','https','h3','quic'].includes(config.type)||typeof config.server!=='string'||!config.server.trim()||config.server.includes('://'))return null;
  const bracket=host=>host.includes(':')?'['+host.replace(/^\[|\]$/g,'')+']':host;
  const port=config.server_port||({udp:53,tcp:53,tls:853,quic:853,https:443,h3:443}[config.type]);
  const secure=['tls','https','h3','quic'].includes(config.type),host=(secure&&config.tls?.server_name||config.server).trim();
  const https=['https','h3'].includes(config.type),scheme=https?'https':config.type;
  return {url:scheme+'://'+bracket(host)+(https&&port===443?'':':'+port)+(https?(config.path||'/dns-query'):''),address:bracket(config.server.trim())+':'+port};
 }
 return {providers,build,detect,apply,validate,endpoint};
})();
