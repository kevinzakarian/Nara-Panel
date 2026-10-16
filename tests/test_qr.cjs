const assert = require('node:assert/strict');
const { test } = require('node:test');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const jsQR = require('jsqr');

const root = path.resolve(__dirname, '..');
const context = vm.createContext({ URL, location: { href: 'https://panel.example.com/AbCdEfGh/#clients' } });
for (const name of ['web/vendor/qrcodegen.js', 'web/subscription-qr.js']) {
 vm.runInContext(fs.readFileSync(path.join(root, name), 'utf8'), context);
}
// Load the real sharing UI without starting its browser event handlers.
const app = fs.readFileSync(path.join(root, 'web/app.js'), 'utf8');
vm.runInContext(app.slice(0, app.indexOf("document.addEventListener('click'")), context);

function decode(svg) {
 const side = Number(svg.match(/viewBox="0 0 (\d+) \d+"/)[1]);
 const scale = 5, width = side * scale;
 const rgba = new Uint8ClampedArray(width * width * 4).fill(255);
 for (const match of svg.matchAll(/M(\d+),(\d+)h1v1h-1z/g)) {
  const x = Number(match[1]), y = Number(match[2]);
  assert.ok(x >= 4 && y >= 4 && x < side - 4 && y < side - 4, 'four-module quiet zone');
  for (let dy = 0; dy < scale; dy++) for (let dx = 0; dx < scale; dx++) {
   const offset = ((y * scale + dy) * width + x * scale + dx) * 4;
   rgba[offset] = rgba[offset + 1] = rgba[offset + 2] = 0;
  }
 }
 const decoded = jsQR(rgba, width, width, { inversionAttempts: 'dontInvert' });
 assert.ok(decoded, 'an independent decoder must read the rendered SVG');
 return decoded.data;
}

const token = 'DemoToken_ABCDEFGHIJKLMNOPQRSTUVWXYZ-0123456789';
for (const [label, subscriptionURL, expectedBase] of [
 ['HTTPS custom subPath', 'https://subscriptions.example.com:8443/DownloadPath/', 'https://subscriptions.example.com:8443/DownloadPath'],
 ['HTTPS origin-only', 'https://subscriptions.example.com:8443', 'https://subscriptions.example.com:8443/subscriptions'],
 ['IPv6 HTTPS', 'https://[2001:db8::1]:10444/Subscriptions', 'https://[2001:db8::1]:10444/Subscriptions'],
 ['HTTP IP and port', 'http://203.0.113.42:10001/DownloadPath/', 'http://203.0.113.42:10001/DownloadPath'],
 ['HTTP origin-only', 'http://subscriptions.example.com:10001', 'http://subscriptions.example.com:10001/subscriptions'],
 ['IPv6 HTTP', 'http://[2001:db8::1]:10001/DownloadPath/', 'http://[2001:db8::1]:10001/DownloadPath'],
 ['long custom subPath', 'https://subscriptions.example.com:8443/' + 'a'.repeat(180) + '/', 'https://subscriptions.example.com:8443/' + 'a'.repeat(180)]
]) {
 test(`sharing UI encodes the independent subscription link: ${label}`, () => {
  context.publicURL=subscriptionURL;context.client={id:'demo-client',token};
  const markup=vm.runInContext("state={settings:{public_url:'https://panel.example.com/PrivatePanel/',subscription_url:publicURL}};subscriptionShare(client,'json')",context);
  assert.equal(decode(markup),expectedBase+'/'+token);
  assert.ok(!decode(markup).includes('PrivatePanel'));
  assert.ok(markup.includes('Download QR'));
 });
 test(`official app QR preserves independent URL and profile name: ${label}`,()=>{
  context.publicURL=subscriptionURL;context.client={id:'demo-client',token,name:'کاربر A & B / + #? 你好'};
  const markup=vm.runInContext("state={settings:{public_url:'https://panel.example.com/PrivatePanel/',subscription_url:publicURL}};subscriptionShare(client)",context);
  const uri=new URL(decode(markup));
  assert.equal(uri.protocol,'sing-box:');assert.equal(uri.host,'import-remote-profile');
  assert.equal(uri.searchParams.get('url'),expectedBase+'/'+token);
  assert.equal(decodeURIComponent(uri.hash.slice(1)),context.client.name);
  assert.equal(uri.searchParams.size,1);
 });
}
test('panel root and rotated tokens never expose the panel URL in subscriptions',()=>{
 context.location.href='https://panel.example.com/#clients';
 for(const suffix of ['old','rotated']){
  context.client={id:'demo-client',token:token+suffix};
  const markup=vm.runInContext("state={settings:{public_url:'https://panel.example.com'}};subscriptionShare(client,'json')",context);
  assert.equal(decode(markup),'http://panel.example.com:10001/subscriptions/'+token+suffix);
 }
 context.location.href='https://panel.example.com/AbCdEfGh/#clients';
});
for(const currentURL of ['http://203.0.113.42:10000/PrivatePanel/#clients','https://panel.example.com/PrivatePanel/#clients','http://[2001:db8::1]:10000/PrivatePanel/#clients','http://203.0.113.42:10000/#clients','http://panel.example.com:10000/PrivatePanel/index.html?preview=1#clients']){
 test(`default subscription address uses its own port/path: ${currentURL}`,()=>{
  context.location.href=currentURL;context.client={id:'demo-client',token};
  try{
   const markup=vm.runInContext("state={settings:{public_url:''}};subscriptionShare(client,'json')",context);
   assert.equal(decode(markup),'http://'+new URL(currentURL).hostname+':10001/subscriptions/'+token);
   assert.ok(!decode(markup).includes('PrivatePanel'));
  }finally{context.location.href='https://panel.example.com/AbCdEfGh/#clients';}
 });
}
test('managed HTTPS subscription has its own public HTTPS port and subPath',()=>{
 context.client={id:'demo-client',token};
 try{
  vm.runInContext("accessSettings={public_host:'panel.example.com',subscription_scheme:'https',subscription_port:8443,sub_path:'/DownloadPath'};state={settings:{public_url:'https://panel.example.com/PrivatePanel'}}",context);
  assert.equal(context.subscriptionURL(context.client),'https://panel.example.com:8443/DownloadPath/'+token);
 }finally{vm.runInContext("accessSettings={subscription_scheme:'http',subscription_port:10001,sub_path:'/subscriptions'}",context);}
});

test('over-capacity links retain copy access with a helpful message', () => {
 context.publicURL = 'https://panel.example.com/' + 'a'.repeat(4000);
 const markup = vm.runInContext("state={settings:{subscription_url:publicURL}};subscriptionShare(client,'json')", context);
 assert.ok(markup.includes('too long for a QR code'));
 assert.ok(markup.includes('Copy link'));
 assert.ok(!markup.includes('Download QR'));
});

for(const succeeds of [true,false]) {
 test(`HTTP clipboard fallback ${succeeds?'copies the link':'offers manual copying when unavailable'}`,async()=>{
  const current='http://203.0.113.42:10000/AbCdEfGh/#clients';
  context.location.href=current;
  context.client={id:'demo-client',token};
  vm.runInContext("state={settings:{public_url:''}}",context);
  let selected=false,removed=false,focused=false,input;
  const previousToast=context.toast;
  context.navigator={};
  context.toast=()=>{};
  context.document={
   activeElement:{focus(){focused=true;}},
   createElement(){return input={select(){selected=true;},remove(){removed=true;}};},
   querySelector(){return {open:true,append(node){assert.equal(node,input);}};},
   execCommand(command){
    assert.equal(command,'copy');assert.ok(selected);
    assert.equal(input.value,'http://203.0.113.42:10001/subscriptions/'+token);
    return succeeds;
   }
  };
  try {
   if(succeeds)await context.copySubscription(context.client,'json');
   else await assert.rejects(context.copySubscription(context.client,'json'),/Select and copy the subscription link/);
   assert.ok(removed);assert.ok(focused);
  } finally {
   context.toast=previousToast;
   delete context.document;delete context.navigator;
   context.location.href='https://panel.example.com/AbCdEfGh/#clients';
  }
 });
}

for(const format of ['sing-box','json']) {
 test(`copy and PNG download use the selected ${format} payload`,async()=>{
  context.client={id:'demo-client',token,name:'Demo profile'};
  vm.runInContext("state={settings:{public_url:'http://203.0.113.42:10000/AbCdEfGh'}}",context);
  const expected=context.subscriptionPayload(context.client,format);
  const originalToast=context.toast;
  let copied,encodedSVG,filename,clicked=false;
  const modal={querySelector(){return {value:format};}};
  const action={dataset:{id:context.client.id},closest(){return modal;}};
  vm.runInContext('state.clients=[client]',context);
  context.navigator={clipboard:{async writeText(value){copied=value;}}};
  context.toast=()=>{};
  context.Image=class {
   set src(value){encodedSVG=decodeURIComponent(value.split(',')[1]);}
   async decode(){this.naturalWidth=512;this.naturalHeight=512;}
  };
  const anchor={click(){clicked=true;filename=this.download;}};
  context.document={
   querySelector(){return modal;},
   createElement(tag){
    if(tag==='a')return anchor;
    assert.equal(tag,'canvas');
    return {getContext(){return {drawImage(){}};},toBlob(callback,type){assert.equal(type,'image/png');callback({});}};
   }
  };
  context.setTimeout=callback=>callback();
  // Keep the host's URL class and blob URL registry untouched.
  const originalURL=context.URL;
  context.URL=class extends URL {static createObjectURL(){return 'blob:demo';}static revokeObjectURL(){}};
  try {
   await context.handle('copy-sub',action);
   assert.equal(copied,expected);
   await context.handle('download-qr',action);
   assert.equal(decode(encodedSVG),expected);
   assert.ok(clicked);
   assert.equal(filename,`nara-subscription-${format}-demo-cli.png`);
  } finally {
   context.toast=originalToast;context.URL=originalURL;
   for(const key of ['navigator','document','Image','setTimeout'])delete context[key];
  }
 });
}

test('changing format replaces only the sharing section and restores selector focus',()=>{
 context.client={id:'demo-client',token,name:'Demo profile'};
 vm.runInContext("state={settings:{public_url:''},clients:[client]}",context);
 let markup,focused=false;
 const share={dataset:{clientId:'demo-client'},set outerHTML(value){markup=value;}};
 const selector={value:'json',closest(){return share;}};
 context.document={querySelector(){return {querySelector(){return {focus(){focused=true;}};}};}};
 try {
  context.changeSubscriptionFormat(selector);
  assert.equal(decode(markup),'http://panel.example.com:10001/subscriptions/'+token);
  assert.ok(markup.includes('value="json" selected'));
  assert.ok(focused);
 } finally {delete context.document;}
});

test('official profile names are encoded as text and unknown formats are rejected',()=>{
 context.client={id:'demo-client',token,name:'<img src=x onerror=alert(1)> & # +'};
 vm.runInContext("state={settings:{public_url:''}}",context);
 const markup=context.subscriptionShare(context.client);
 assert.ok(!markup.includes('<img'));
 assert.equal(decodeURIComponent(new URL(decode(markup)).hash.slice(1)),context.client.name);
 assert.throws(()=>context.subscriptionPayload(context.client,'clash'),/Unsupported subscription format/);
});
