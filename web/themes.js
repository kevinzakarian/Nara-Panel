'use strict';
const NaraTheme=(()=>{
 const skins=['ember','volt','lagoon'],modes=['light','dark','system'];
 const preference=window.matchMedia?.('(prefers-color-scheme: dark)');
 let current={skin:'ember',color_mode:'light'};
 function apply(settings={},persist=false){
  current={skin:skins.includes(settings.skin)?settings.skin:'ember',color_mode:modes.includes(settings.color_mode)?settings.color_mode:'light'};
  const root=document.documentElement;root.dataset.skin=current.skin;root.dataset.mode=current.color_mode==='system'?(preference?.matches?'dark':'light'):current.color_mode;
  if(persist)try{localStorage.setItem('nara:appearance',JSON.stringify(current));}catch{}
 }
 try{apply(JSON.parse(localStorage.getItem('nara:appearance')||'{}'));}catch{apply();}
 preference?.addEventListener('change',()=>{if(current.color_mode==='system')apply(current);});
 return {apply};
})();
