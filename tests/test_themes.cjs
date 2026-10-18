const {test}=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),{JSDOM}=require('jsdom');
test('three palettes support both modes, device changes and resilient local preview',()=>{
 const dom=new JSDOM('<!doctype html><html></html>',{runScripts:'outside-only',url:'http://localhost/Panel/'}),w=dom.window;let changed;const preference={matches:false,addEventListener(event,handler){changed=handler}};w.matchMedia=()=>preference;
 w.eval(fs.readFileSync('web/themes.js','utf8')+'\nglobalThis.Theme=NaraTheme;');
 for(const skin of ['ember','volt','lagoon'])for(const color_mode of ['light','dark']){w.Theme.apply({skin,color_mode},true);assert.equal(w.document.documentElement.dataset.skin,skin);assert.equal(w.document.documentElement.dataset.mode,color_mode);assert.equal(JSON.parse(w.localStorage.getItem('nara:appearance')).skin,skin);}
 w.Theme.apply({skin:'lagoon',color_mode:'system'});preference.matches=true;changed();assert.equal(w.document.documentElement.dataset.mode,'dark');preference.matches=false;changed();assert.equal(w.document.documentElement.dataset.mode,'light');
 w.Theme.apply({skin:'bad',color_mode:'bad'});assert.equal(w.document.documentElement.dataset.skin,'ember');assert.equal(w.document.documentElement.dataset.mode,'light');dom.window.close();
});
test('live connection badges distinguish account eligibility, unavailable monitoring and stopped core',()=>{
 const dom=new JSDOM('<div id="content"><table><tbody><tr><td><input id="selection" type="checkbox" checked></td><td data-client-status="one"></td></tr></tbody></table></div>',{runScripts:'outside-only',url:'http://localhost/Panel/'}),w=dom.window;
 const source=fs.readFileSync('web/app.js','utf8');w.eval(fs.readFileSync('web/clients.js','utf8')+'\n'+source.slice(0,source.indexOf("document.addEventListener('click'"))+`\nglobalThis.Badges={setup(c,d){state={clients:[c]};dashboard=d},html:clientConnectionHTML,refresh:refreshClientConnections};`);
 const client={id:'one',name:'Sample',enabled:true},dashboard={totals:{},core:{running:true,presence:{available:true,counts:{one:2}}}};w.Badges.setup(client,dashboard);assert.match(w.Badges.html(client),/Online · 2 connections/);const selection=w.document.querySelector('#selection');w.Badges.refresh();assert.equal(w.document.querySelector('#selection'),selection);assert.equal(selection.checked,true);
 dashboard.core.presence.available=false;w.Badges.refresh();assert.match(w.document.body.textContent,/Status unavailable/);assert.doesNotMatch(w.document.body.textContent,/Online/);
 dashboard.core.running=false;assert.match(w.Badges.html(client),/Offline/);dashboard.core.running=true;dashboard.core.presence.available=true;client.enabled=false;assert.match(w.Badges.html(client),/Offline/);dom.window.close();
});
test('Settings offers exactly three skins and light, dark or device appearance',()=>{
 const dom=new JSDOM('<!doctype html>',{runScripts:'outside-only',url:'http://localhost/Panel/'}),w=dom.window;const source=fs.readFileSync('web/app.js','utf8');w.eval(source.slice(0,source.indexOf("document.addEventListener('click'"))+`\nstate={settings:{skin:'lagoon',color_mode:'dark'}};document.body.innerHTML=renderAppearanceSettings();`);assert.equal(w.document.querySelectorAll('[name=skin]').length,3);assert.equal(w.document.querySelector('[name=skin]:checked').value,'lagoon');assert.equal(w.document.querySelectorAll('[name=color_mode]').length,3);assert.equal(w.document.querySelector('[name=color_mode]:checked').value,'dark');dom.window.close();
});
