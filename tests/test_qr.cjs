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
for (const [label, publicURL, expectedBase] of [
 ['custom webPath', 'https://panel.example.com/AbCdEfGh/', 'https://panel.example.com/AbCdEfGh'],
 ['origin-only settings', 'https://panel.example.com', 'https://panel.example.com/AbCdEfGh'],
 ['IPv6 with port', 'https://[2001:db8::1]:10443/AbCdEfGh', 'https://[2001:db8::1]:10443/AbCdEfGh'],
 ['HTTP with IP, port and webPath', 'http://203.0.113.42:10000/AbCdEfGh/', 'http://203.0.113.42:10000/AbCdEfGh'],
 ['HTTP origin-only settings', 'http://panel.example.com:10000', 'http://panel.example.com:10000/AbCdEfGh'],
 ['HTTP IPv6 with port', 'http://[2001:db8::1]:10000/AbCdEfGh/', 'http://[2001:db8::1]:10000/AbCdEfGh'],
 ['long public URL', 'https://panel.example.com/' + 'a'.repeat(180) + '/', 'https://panel.example.com/' + 'a'.repeat(180)]
]) {
 test(`sharing UI encodes the exact subscription link: ${label}`, () => {
  context.publicURL = publicURL;
  context.client = { id: 'demo-client', token };
  const markup = vm.runInContext("state={settings:{public_url:publicURL}};subscriptionShare(client,'json')", context);
  assert.equal(decode(markup), expectedBase + '/sub/' + token);
  assert.ok(markup.includes('Download QR'));
 });
 test(`official app QR preserves the remote profile URL and name: ${label}`, () => {
  context.publicURL=publicURL;
  context.client={id:'demo-client',token,name:'کاربر A & B / + #? 你好'};
  const markup=vm.runInContext('state={settings:{public_url:publicURL}};subscriptionShare(client)',context);
  const payload=decode(markup),uri=new URL(payload);
  assert.equal(uri.protocol,'sing-box:');
  assert.equal(uri.host,'import-remote-profile');
  assert.equal(uri.searchParams.get('url'),expectedBase+'/sub/'+token);
  assert.equal(decodeURIComponent(uri.hash.slice(1)),context.client.name);
  assert.equal(uri.searchParams.size,1,'encoded URL must remain a single parameter');
  assert.ok(markup.includes('value="sing-box" selected'));
  assert.ok(markup.includes('JSON subscription URL'));
 });
}

test('legacy root path and rotated token generate fresh QR codes', () => {
 context.location.href = 'https://panel.example.com/#clients';
 context.publicURL = 'https://panel.example.com';
 for (const suffix of ['old', 'rotated']) {
  context.client = { id: 'demo-client', token: token + suffix };
  const markup = vm.runInContext("state={settings:{public_url:publicURL}};subscriptionShare(client,'json')", context);
  assert.equal(decode(markup), 'https://panel.example.com/sub/' + token + suffix);
 }
 context.location.href = 'https://panel.example.com/AbCdEfGh/#clients';
});

for(const currentURL of [
 'http://203.0.113.42:10000/AbCdEfGh/#clients',
 'https://panel.example.com/AbCdEfGh/#clients',
 'http://[2001:db8::1]:10000/AbCdEfGh/#clients',
 'http://203.0.113.42:10000/#clients',
 'http://panel.example.com:10000/AbCdEfGh/index.html?preview=1#clients'
]) {
 test(`blank public URL produces a QR from the current address: ${currentURL}`, () => {
  context.location.href=currentURL;
  context.client={id:'demo-client',token};
  try {
   const markup=vm.runInContext("state={settings:{public_url:''}};subscriptionShare(client,'json')",context);
   assert.equal(decode(markup),new URL('.',currentURL).href+'sub/'+token);
   assert.ok(markup.includes('Copy link'));
   assert.ok(markup.includes('Download QR'));
   assert.ok(!markup.includes('Set the panel'));
  } finally {context.location.href='https://panel.example.com/AbCdEfGh/#clients';}
 });
}

test('configured HTTPS public URL takes precedence over the current HTTP address', () => {
 context.location.href='http://203.0.113.42:10000/AbCdEfGh/#clients';
 try {
  const markup=vm.runInContext("state={settings:{public_url:'https://panel.example.com'}};subscriptionShare(client,'json')",context);
  assert.equal(decode(markup),'https://panel.example.com/AbCdEfGh/sub/'+token);
 } finally {context.location.href='https://panel.example.com/AbCdEfGh/#clients';}
});

test('over-capacity links retain copy access with a helpful message', () => {
 context.publicURL = 'https://panel.example.com/' + 'a'.repeat(4000);
 const markup = vm.runInContext("state={settings:{public_url:publicURL}};subscriptionShare(client,'json')", context);
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
    assert.equal(input.value,new URL('.',current).href+'sub/'+token);
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
  assert.equal(decode(markup),'https://panel.example.com/AbCdEfGh/sub/'+token);
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
