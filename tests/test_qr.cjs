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
 ['long public URL', 'https://panel.example.com/' + 'a'.repeat(180) + '/', 'https://panel.example.com/' + 'a'.repeat(180)]
]) {
 test(`sharing UI encodes the exact subscription link: ${label}`, () => {
  context.publicURL = publicURL;
  context.client = { id: 'demo-client', token };
  const markup = vm.runInContext('state={settings:{public_url:publicURL}};subscriptionShare(client)', context);
  assert.equal(decode(markup), expectedBase + '/sub/' + token);
  assert.ok(markup.includes('Download QR'));
 });
}

test('legacy root path and rotated token generate fresh QR codes', () => {
 context.location.href = 'https://panel.example.com/#clients';
 context.publicURL = 'https://panel.example.com';
 for (const suffix of ['old', 'rotated']) {
  context.client = { id: 'demo-client', token: token + suffix };
  const markup = vm.runInContext('state={settings:{public_url:publicURL}};subscriptionShare(client)', context);
  assert.equal(decode(markup), 'https://panel.example.com/sub/' + token + suffix);
 }
 context.location.href = 'https://panel.example.com/AbCdEfGh/#clients';
});

test('missing public URL offers settings and exposes no QR or token', () => {
 const markup = vm.runInContext("state={settings:{public_url:''}};subscriptionShare(client)", context);
 assert.ok(markup.includes('Open settings'));
 assert.ok(!markup.includes('<svg xmlns='));
 assert.ok(!markup.includes(token));
});

test('over-capacity links retain copy access with a helpful message', () => {
 context.publicURL = 'https://panel.example.com/' + 'a'.repeat(4000);
 const markup = vm.runInContext('state={settings:{public_url:publicURL}};subscriptionShare(client)', context);
 assert.ok(markup.includes('too long for a QR code'));
 assert.ok(markup.includes('Copy link'));
 assert.ok(!markup.includes('Download QR'));
});
