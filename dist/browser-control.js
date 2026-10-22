/* Direct, authenticated input to the same real browser the agent uses. */
(() => {
  const image=document.querySelector('#browser-image'),view=document.querySelector('#browser-view'),toolbar=document.querySelector('#preview-toolbar');
  const nav=document.createElement('form');nav.id='browser-navigation';nav.setAttribute('aria-label','Browser navigation');
  const address=document.createElement('input');address.type='text';address.placeholder='Enter a web address';address.setAttribute('aria-label','Browser address');
  const notify=error=>window.dispatchEvent(new CustomEvent('vision:error',{detail:error}));
  async function action(body){const response=await fetch('/api/browser/control',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});const result=await response.json();if(!response.ok)throw Error(result.detail||'Browser action failed');return result;}
  function button(label,title,run){const element=document.createElement('button');element.type='button';element.textContent=label;element.title=title;element.setAttribute('aria-label',title);element.onclick=()=>Promise.resolve().then(run).catch(notify);return element;}
  const paste=()=>navigator.clipboard.readText().then(text=>send({action:'text',text}));
  nav.append(button('←','Browser back',()=>action({action:'back'})),button('→','Browser forward',()=>action({action:'forward'})),button('↻','Reload browser',()=>action({action:'reload'})),address,button('Go','Go to address',()=>action({action:'navigate',url:address.value})),button('Paste','Paste into browser',paste),button('Unmute video','Unmute video and page media',()=>action({action:'unmute'})));
  nav.onsubmit=event=>{event.preventDefault();action({action:'navigate',url:address.value}).catch(notify);};view.prepend(nav);
  const open=button('Browser','Open browser preview',()=>{const select=document.querySelector('#preview-select');if(!select.querySelector('option[value=browser]'))select.append(new Option('Live browser','browser'));select.value='browser';select.dispatchEvent(new Event('change'));address.focus();});open.className='preview-browser-icon';open.innerHTML='<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3a18 18 0 0 1 0 18 18 18 0 0 1 0-18Z"/></svg>';toolbar.append(open);
  window.VisionBrowser={open:async url=>{try{if(!document.querySelector('main').hidden)document.querySelector('#open-chat').click();open.click();await action({action:'navigate',url});return true;}catch(error){notify(error);return false;}}};
  const expand=button('Expand','Expand preview',async()=>{const panel=document.querySelector('.central-grid');if(document.fullscreenElement===panel)await document.exitFullscreen();else await panel.requestFullscreen();});expand.className='preview-text-button';toolbar.append(expand);
  document.addEventListener('fullscreenchange',()=>expand.textContent=document.fullscreenElement?'Restore':'Expand');
  let remote={width:1280,height:800},dragging=false,lastMove=0,sendQueue=Promise.resolve();
  const send=body=>{sendQueue=sendQueue.then(()=>action(body)).catch(notify);return sendQueue;};
  window.addEventListener('vision:browser-frame',event=>{remote=event.detail;if(document.activeElement!==address)address.value=remote.url||'';});
  image.tabIndex=0;image.draggable=false;image.setAttribute('role','application');image.setAttribute('aria-label','Interactive browser preview. Click to interact; use the keyboard to type.');
  function point(event){const rect=image.getBoundingClientRect(),ratio=Math.min(rect.width/remote.width,rect.height/remote.height),left=rect.left+(rect.width-remote.width*ratio)/2;const x=(event.clientX-left)/ratio,y=(event.clientY-rect.top)/ratio;return {x,y,inside:x>=0&&y>=0&&x<remote.width&&y<remote.height};}
  image.addEventListener('pointerdown',event=>{const p=point(event);if(!p.inside)return;event.preventDefault();image.focus();dragging=true;image.setPointerCapture(event.pointerId);send({action:'down',x:p.x,y:p.y,button:['left','middle','right'][event.button]||'left',click_count:event.detail===2?2:1});});
  image.addEventListener('pointermove',event=>{if(!dragging||performance.now()-lastMove<70)return;lastMove=performance.now();send({action:'move',...point(event)});});
  const release=event=>{if(!dragging)return;dragging=false;send({action:'up',...point(event),button:['left','middle','right'][event.button]||'left'});};image.addEventListener('pointerup',release);image.addEventListener('pointercancel',release);
  image.addEventListener('wheel',event=>{event.preventDefault();const p=point(event);send({action:'move',x:p.x,y:p.y});send({action:'scroll',dx:event.deltaX,dy:event.deltaY});},{passive:false});
  image.addEventListener('contextmenu',event=>event.preventDefault());
  image.addEventListener('keydown',event=>{
    if((event.ctrlKey||event.metaKey)&&event.key.toLowerCase()==='l'){event.preventDefault();address.focus();address.select();return;}
    if((event.ctrlKey||event.metaKey)&&event.key.toLowerCase()==='v'){event.preventDefault();paste().catch(notify);return;}
    event.preventDefault();if((event.ctrlKey||event.metaKey)&&event.key.toLowerCase()==='c'){action({action:'selection'}).then(result=>VisionUI.copyText(result.text)).catch(notify);return;}
    if(event.key.length===1&&!event.ctrlKey&&!event.metaKey&&!event.altKey){send({action:'text',text:event.key});return;}
    if(['Control','Shift','Alt','Meta','CapsLock'].includes(event.key))return;
    const key=(event.ctrlKey?'Control+':'')+(event.metaKey?'Meta+':'')+(event.altKey?'Alt+':'')+(event.shiftKey?'Shift+':'')+event.key;send({action:'key',key});
  });
  image.addEventListener('paste',event=>{event.preventDefault();send({action:'text',text:event.clipboardData?.getData('text/plain')||''});});
})();
