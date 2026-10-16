'use strict';

// All encoding stays in the browser; subscription tokens never leave the panel.
globalThis.NaraQR = Object.freeze({
 svg(text) {
  if (typeof text !== 'string' || !text) throw new Error('A subscription link is required.');
  const qr = qrcodegen.QrCode.encodeText(text, qrcodegen.QrCode.Ecc.MEDIUM);
  const side = qr.size + 8; // Four white modules on every side for reliable scanning.
  const modules = [];
  for (let y = 0; y < qr.size; y++) {
   for (let x = 0; x < qr.size; x++) {
    if (qr.getModule(x, y)) modules.push(`M${x + 4},${y + 4}h1v1h-1z`);
   }
  }
  return `<svg xmlns="http://www.w3.org/2000/svg" width="${side * 8}" height="${side * 8}" viewBox="0 0 ${side} ${side}" role="img" aria-label="Subscription QR code" shape-rendering="crispEdges"><rect width="${side}" height="${side}" fill="#fff"/><path d="${modules.join('')}" fill="#000"/></svg>`;
 }
});
