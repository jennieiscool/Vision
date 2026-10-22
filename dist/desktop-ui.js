/* Desktop chrome, custom pickers/dialogs, profile entry and application lock. */
(() => {
  const node=(tag,cls,text)=>{const el=document.createElement(tag);if(cls)el.className=cls;if(text!==undefined)el.textContent=text;return el;};
  const api=async(path,body)=>{const response=await fetch('/api/'+path,body===undefined?{}:{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});const result=await response.json();if(!response.ok)throw Error(result.detail||'This action could not be completed.');return result;};
  const bar=node('header','desktop-titlebar');bar.innerHTML='<div class="desktop-brand"><img src="vision-mark.svg" alt=""><span>Vision</span></div><div class="desktop-window-actions"></div>';document.body.prepend(bar);
  for(const [action,label,svg] of [['minimize','Minimize','M5 12h14'],['maximize','Maximize','M5 5h14v14H5Z'],['close','Close Vision','m6 6 12 12M18 6 6 18']]){const button=node('button','window-action');button.setAttribute('aria-label',label);button.title=label;button.innerHTML='<svg viewBox="0 0 24 24"><path d="'+svg+'"/></svg>';button.onclick=()=>window.VisionDesktop?.window(action);bar.lastChild.append(button);}
  if(!window.VisionDesktop)bar.hidden=true;else document.body.classList.add('desktop-app');
  let activePicker;
  function enhanceSelect(select){
    if(select.dataset.custom)return;select.dataset.custom='true';select.classList.add('native-select-source');const preview=select.id==='preview-select';
    const wrap=node('div','vision-picker'),button=node('button','picker-button'),list=node('div','picker-list');button.type='button';button.setAttribute('aria-haspopup',preview?'dialog':'listbox');list.setAttribute('role',preview?'dialog':'listbox');if(preview)list.setAttribute('aria-label','Opened previews');list.hidden=true;select.after(wrap);wrap.append(button,list);
    const close=()=>{list.hidden=true;button.setAttribute('aria-expanded','false');};
    const sync=()=>{
      const label=node('span','picker-label',select.selectedOptions[0]?.textContent||'Select'),chevron=node('span','picker-chevron');chevron.setAttribute('aria-hidden','true');button.replaceChildren(label,chevron);button.disabled=select.disabled;button.setAttribute('aria-label',select.getAttribute('aria-label')||'Choose an option');list.replaceChildren();
      for(const option of select.options){
        const item=node('button','picker-option',option.textContent);item.type='button';item.setAttribute('role',preview?'button':'option');item.setAttribute(preview?'aria-pressed':'aria-selected',String(option.selected));item.disabled=option.disabled;item.dataset.value=option.value;
        item.onclick=()=>{select.value=option.value;select.dispatchEvent(new Event('change',{bubbles:true}));close();sync();button.focus();};
        if(!preview){list.append(item);continue;}
        const row=node('div','picker-preview-row');row.append(item);
        if(option.value!=='grid'){
          const remove=node('button','picker-preview-remove');remove.type='button';remove.title='Remove '+option.textContent;remove.setAttribute('aria-label',remove.title);remove.innerHTML='<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 7h16M9 3h6l1 4M6 7l1 14h10l1-14M10 10v8M14 10v8"/></svg>';
          remove.onclick=async event=>{event.stopPropagation();remove.disabled=true;try{await VisionWorkspace.closeItems([option.value]);sync();list.querySelector('.picker-option')?.focus();}catch(error){window.dispatchEvent(new CustomEvent('vision:error',{detail:error}));}finally{remove.disabled=false;}};row.append(remove);
        }
        list.append(row);
      }
      if(preview&&select.options.length>1){const clear=node('button','picker-clear-previews','Clear all previews');clear.type='button';clear.onclick=async()=>{close();if(await modal('Clear opened previews?',{text:'Your original files and saved applications will remain.',confirm:'Clear previews'})){try{await VisionWorkspace.closeItems(VisionUI.openedPreviews(),true);sync();button.focus();}catch(error){window.dispatchEvent(new CustomEvent('vision:error',{detail:error}));}}};list.append(clear);}
    };
    button.onclick=()=>{if(activePicker&&activePicker!==list)activePicker.hidden=true;list.hidden=!list.hidden;activePicker=list;button.setAttribute('aria-expanded',String(!list.hidden));if(!list.hidden){const r=button.getBoundingClientRect();list.style.left=Math.max(8,Math.min(r.left,innerWidth-300))+'px';list.style.top=Math.max(8,Math.min(r.bottom+6,innerHeight-Math.min(290,list.scrollHeight)-12))+'px';list.style.minWidth=Math.max(preview?260:200,Math.min(380,r.width))+'px';list.querySelector(preview?'[aria-pressed=true]':'[aria-selected=true]')?.focus();}};
    list.onkeydown=event=>{const items=[...list.querySelectorAll('button:not(:disabled)')],index=items.indexOf(document.activeElement);if(event.key==='Escape'){event.preventDefault();close();button.focus();}if(preview&&event.key==='Delete'){event.preventDefault();event.target.closest('.picker-preview-row')?.querySelector('.picker-preview-remove')?.click();}if(['ArrowDown','ArrowUp','Home','End'].includes(event.key)){event.preventDefault();const next=event.key==='Home'?0:event.key==='End'?items.length-1:(index+(event.key==='ArrowDown'?1:items.length-1))%items.length;items[next]?.focus();}};
    new MutationObserver(sync).observe(select,{childList:true,subtree:true,attributes:true});select.addEventListener('change',sync);select.addEventListener('vision:selection-sync',sync);sync();
  }
  document.addEventListener('click',event=>{if(event.target.closest('#open-chat,#back')&&activePicker)activePicker.hidden=true;},true);
  document.addEventListener('pointerdown',event=>{if(activePicker&&!activePicker.contains(event.target)&&!event.target.closest('.vision-picker'))activePicker.hidden=true;});
  const observer=new MutationObserver(records=>{for(const record of records)for(const element of record.addedNodes)if(element.nodeType===1){if(element.matches('select'))enhanceSelect(element);element.querySelectorAll('select').forEach(enhanceSelect);}});observer.observe(document.body,{childList:true,subtree:true});document.querySelectorAll('select').forEach(enhanceSelect);
  function modal(title,{text='',input=false,value='',confirm='Continue',danger=false}={}){
    return new Promise(resolve=>{const overlay=node('div','vision-modal-layer'),panel=node('section','vision-dialog');panel.setAttribute('role','dialog');panel.setAttribute('aria-modal','true');const heading=node('h2','',title),description=node('p','',text),field=node('input','dialog-input');heading.id='dialog-'+Date.now();panel.setAttribute('aria-labelledby',heading.id);panel.append(heading,description);if(input){field.value=value;panel.append(field);}const actions=node('div','dialog-actions'),cancel=node('button','secondary','Cancel'),ok=node('button',danger?'danger':'primary',confirm);actions.append(cancel,ok);panel.append(actions);overlay.append(panel);document.body.append(overlay);let finishing=false;splitMotion(overlay,true,'.vision-dialog').then(()=>{if(!finishing)(input?field:ok).focus();});const finish=async result=>{if(finishing)return;finishing=true;await splitMotion(overlay,false,'.vision-dialog');overlay.remove();resolve(result);};cancel.onclick=()=>finish(null);ok.onclick=()=>finish(input?field.value:true);panel.onkeydown=e=>{if(e.key==='Tab'){const first=input?field:cancel;const last=ok;if(e.shiftKey&&document.activeElement===first){e.preventDefault();last.focus();}else if(!e.shiftKey&&document.activeElement===last){e.preventDefault();first.focus();}}if(e.key==='Escape')finish(null);if(e.key==='Enter'&&e.target.tagName!=='TEXTAREA')ok.click();};(input?field:ok).focus();});
  }
  async function splitMotion(layer,opening,selector='.vision-settings'){
    const box=layer.querySelector(selector);if(!box)return;
    const sequence=(layer._motionSequence||0)+1;layer._motionSequence=sequence;
    for(const ghost of layer._motionGhosts||[])ghost.remove();layer._motionGhosts=[];
    box.style.visibility='hidden';layer.hidden=false;
    if(opening){layer.classList.remove('sheet-closing');layer.classList.add('sheet-visible');}else layer.classList.add('sheet-closing');
    await new Promise(resolve=>requestAnimationFrame(resolve));if(sequence!==layer._motionSequence)return;
    const rect=box.getBoundingClientRect(),reduced=matchMedia('(prefers-reduced-motion: reduce)').matches;
    const animations=[];
    for(const upper of [true,false]){
      const ghost=node('div','dialog-motion-half');ghost.setAttribute('aria-hidden','true');ghost.inert=true;
      Object.assign(ghost.style,{left:rect.left+'px',top:(rect.top+(upper?0:rect.height/2))+'px',width:rect.width+'px',height:(rect.height/2)+'px',transformOrigin:upper?'50% 100%':'50% 0'});
      // Expand the empty frame first. Contents appear only once it is open.
      const clone=box.cloneNode(false);clone.classList.add('dialog-motion-clone');clone.removeAttribute('id');
      Object.assign(clone.style,{width:rect.width+'px',height:rect.height+'px',position:'absolute',top:upper?'0':(-rect.height/2)+'px',left:'0',visibility:'visible',margin:'0',opacity:'1',transform:'none',clipPath:'none'});
      ghost.append(clone);document.body.append(ghost);layer._motionGhosts.push(ghost);
      // Keep the full width steady; only height unfolds from the center seam.
      const folded={transform:'scaleY(0)',opacity:1};
      const spread={transform:'scaleY(1)',opacity:1};
      const animation=ghost.animate(opening?[folded,spread]:[spread,folded],{duration:reduced?1:opening?900:480,easing:opening?'cubic-bezier(.22,.61,.36,1)':'cubic-bezier(.6,0,.8,.3)',fill:'forwards'});
      animations.push(animation.finished.catch(()=>{}));
    }
    await Promise.all(animations);if(sequence!==layer._motionSequence)return;
    for(const ghost of layer._motionGhosts)ghost.remove();layer._motionGhosts=[];box.style.visibility='';
    if(opening&&!reduced){for(const content of box.children)if(!content.classList.contains('settings-split-line'))content.animate([{opacity:0},{opacity:1}],{duration:240,easing:'ease-out'});}
    if(!opening){layer.hidden=true;layer.classList.remove('sheet-visible','sheet-closing');}
  }
  const openSheet=(layer,selector)=>splitMotion(layer,true,selector);
  const closeSheet=(layer,selector)=>splitMotion(layer,false,selector);
  let lockLayer;
  async function showLock(){
    if(lockLayer)return;document.querySelectorAll('main,#workspace,.vision-settings-layer,.profile-entry').forEach(el=>el.inert=true);window.VisionAudio?.controller.mute();
    lockLayer=node('div','lock-screen');lockLayer.innerHTML='<img src="vision-mark.svg" alt=""><h1>Vision is locked</h1><p>Your workspace is waiting for you.</p>';
    const password=node('input','lock-password');password.type='password';password.placeholder='App password';password.setAttribute('aria-label','App password');const error=node('p','lock-error'),unlock=node('button','primary','Unlock'),hello=node('button','secondary','Unlock with Windows Hello');lockLayer.append(password,unlock,hello,error);document.body.append(lockLayer);
    const finish=()=>{lockLayer.remove();lockLayer=null;document.querySelectorAll('main,#workspace,.vision-settings-layer,.profile-entry').forEach(el=>el.inert=false);window.dispatchEvent(new Event('vision:refresh-history'));};
    unlock.onclick=async()=>{try{await api('desktop/security',{action:'unlock',password:password.value});finish();}catch(e){error.textContent=e.message;}};password.onkeydown=e=>{if(e.key==='Enter')unlock.click();};
    hello.hidden=!window.VisionDesktop;hello.onclick=async()=>{try{const result=await VisionDesktop.hello('verify');if(result.result==='Verified')finish();else error.textContent='Windows Hello did not verify your identity. Use your app password.';}catch(e){error.textContent=e.message;}};password.focus();
  }
  async function profileEntry(){
    const overlay=node('div','profile-entry');overlay.innerHTML='<img class="entry-mark" src="vision-mark.svg" alt=""><h1>Welcome to Vision</h1><p>Choose your space.</p><div class="entry-profiles"></div><p class="entry-status" role="status">Connecting to your engine…</p>';document.body.append(overlay);
    let stopped=false;
    const load=async()=>{if(stopped)return;try{if(lockLayer){setTimeout(load,1800);return;}const data=await api('desktop/profiles');const list=overlay.querySelector('.entry-profiles');list.replaceChildren();for(const profile of data.profiles){const button=node('button','profile-card'),avatar=node('span','profile-avatar',(profile.name==='default'?data.display_name:profile.name).slice(0,1).toUpperCase()),name=node('strong','',profile.name==='default'?data.display_name:profile.name),description=node('small','',profile.description|| (profile.name===data.active?'Current profile':'Separate memory and conversation'));button.append(avatar,name,description);button.onclick=async()=>{button.disabled=true;try{if(profile.name!==data.active)await api('desktop/profiles',{action:'switch',name:profile.name});stopped=true;overlay.classList.add('entry-leaving');setTimeout(()=>overlay.remove(),350);window.dispatchEvent(new Event('vision:refresh-history'));}catch(e){overlay.querySelector('.entry-status').textContent=e.message;button.disabled=false;}};list.append(button);}const add=node('button','profile-card profile-add','+ New profile');add.onclick=()=>window.VisionSettings.createProfile();list.append(add);overlay.querySelector('.entry-status').textContent='';}catch(e){overlay.querySelector('.entry-status').textContent=e.message;setTimeout(load,1800);}};
    window.addEventListener('vision:profiles-updated',load);load();
  }
  window.VisionShell={api,modal,openSheet,closeSheet,showLock,enhanceSelect};
  api('desktop/security').then(state=>{profileEntry();if(state.locked)showLock();}).catch(()=>profileEntry());
})();
