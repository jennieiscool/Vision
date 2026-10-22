/* Optional native conversations stay inside the existing right-hand chat panel. */
(() => {
  const panel=document.querySelector('.conversation'),header=panel.querySelector('.panel-header');
  const el=(tag,cls,text)=>{const n=document.createElement(tag);if(cls)n.className=cls;if(text!==undefined)n.textContent=text;return n;};
  const api=async(path,data)=>{const r=await fetch('/api/'+path,data===undefined?{}:{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)});let value;try{value=await r.json();}catch{throw Error('The conversation service could not complete this action.');}if(!r.ok)throw Error(value.detail||'The conversation could not open.');return value;};
  const error=e=>window.dispatchEvent(new CustomEvent('vision:error',{detail:e}));
  let state={active:'main',main:{id:'main',title:'Main'},sides:[],connected:false,busy:false},changing=false,loading=false;
  const controls=el('div','conversation-controls'),plus=el('button','conversation-action'),more=el('button','conversation-action');plus.type=more.type='button';plus.title='New side conversation';plus.setAttribute('aria-label',plus.title);plus.innerHTML='<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 5v14M5 12h14"/></svg>';more.title='Conversation menu';more.setAttribute('aria-label',more.title);more.setAttribute('aria-expanded','false');more.setAttribute('aria-haspopup','menu');more.innerHTML='<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="5" cy="12" r="1.5"/><circle cx="12" cy="12" r="1.5"/><circle cx="19" cy="12" r="1.5"/></svg>';controls.append(plus,more);header.querySelector('.panel-mark')?.remove();header.append(controls);
  const tabs=el('nav','conversation-tabs');tabs.setAttribute('aria-label','Conversations');const main=el('button','conversation-tab conversation-main','Main'),sides=el('div','conversation-side-tabs');main.type='button';main.title='Main conversation';tabs.append(main,sides);header.after(tabs);
  const menu=el('div','conversation-menu');menu.hidden=true;menu.setAttribute('role','menu');menu.setAttribute('aria-label','Conversation menu');panel.append(menu);
  const closeMenu=()=>{menu.hidden=true;more.setAttribute('aria-expanded','false');};
  const button=(label,action,parent,cls='conversation-menu-item')=>{const b=el('button',cls,label);b.type='button';b.onclick=()=>Promise.resolve().then(action).catch(error);parent.append(b);return b;};
  button('Recent chats',()=>{closeMenu();return showList('recent');},menu);button('New side conversation',()=>{closeMenu();return create();},menu);button('All side conversations',()=>{closeMenu();return showList('sides');},menu);
  function render(){main.setAttribute('aria-current',String(state.active==='main'));main.disabled=changing||state.busy||loading;main.onclick=()=>switchTo({action:'switch',id:'main'}).catch(error);sides.replaceChildren();for(const item of state.sides){const b=button(item.title||'Side conversation',()=>switchTo({action:'switch',id:item.id}),sides,'conversation-tab');b.title=item.title||'Side conversation';b.setAttribute('aria-current',String(state.active===item.id));b.disabled=changing||state.busy||loading;}
    plus.disabled=changing||state.busy||loading||!state.connected;more.disabled=changing;for(const b of menu.querySelectorAll('button'))b.disabled=changing;
  }
  async function refresh(){state=await api('conversations');render();}
  async function switchTo(data){if(changing)return false;if(state.busy)throw Error('Finish or stop the current response before switching conversations.');if(data.action==='switch'&&data.id===state.active)return true;
    VisionChat.prepareSwitch();changing=true;closeMenu();render();try{state=await api('conversations',data);render();await VisionChat.reload();return true;}finally{changing=false;VisionChat.finishSwitch();render();}}
  async function create(){const title=await VisionShell.modal('New side conversation',{input:true,value:'Side conversation',confirm:'Create'});if(title===null)return;await switchTo({action:'create',title:title.trim()||'Side conversation'});}
  plus.onclick=()=>create().catch(error);
  more.onclick=()=>{menu.hidden=!menu.hidden;more.setAttribute('aria-expanded',String(!menu.hidden));if(!menu.hidden)menu.querySelector('button')?.focus();};
  menu.onkeydown=event=>{const buttons=[...menu.querySelectorAll('button:not(:disabled)')],index=buttons.indexOf(document.activeElement);if(event.key==='Escape'){event.preventDefault();closeMenu();more.focus();}if(event.key==='Tab')closeMenu();if(['ArrowDown','ArrowUp'].includes(event.key)){event.preventDefault();buttons[(index+(event.key==='ArrowDown'?1:buttons.length-1))%buttons.length]?.focus();}};
  document.addEventListener('pointerdown',event=>{if(!menu.contains(event.target)&&!more.contains(event.target))closeMenu();});
  async function showList(mode){
    const data=mode==='recent'?await api('conversations/recent'):await api('conversations'),items=mode==='recent'?data.sessions:data.sides;
    const layer=el('div','vision-modal-layer'),dialog=el('section','vision-dialog conversation-dialog'),title=el('h2','',mode==='recent'?'Recent chats':'Side conversations'),list=el('div','conversation-history-list'),status=el('p','conversation-list-status');title.id='vision-conversation-picker-title';dialog.setAttribute('role','dialog');dialog.setAttribute('aria-modal','true');dialog.setAttribute('aria-labelledby',title.id);dialog.append(title,list,status);const previous=document.activeElement;let closing=false;
    const close=async()=>{if(closing)return;closing=true;await VisionShell.closeSheet(layer,'.conversation-dialog');layer.remove();if(previous?.isConnected)previous.focus();};
    if(!items?.length)list.append(el('p','conversation-list-empty',mode==='recent'?'No other saved conversations yet.':'No side conversations yet.'));
    for(const item of items||[]){const row=button(item.title||'Untitled conversation',async()=>{row.disabled=true;try{const ok=await switchTo(mode==='recent'?{action:'recent',session_id:item.id,title:item.title||'Side conversation'}:{action:'switch',id:item.id});if(ok)await close();}catch(e){status.textContent=e.message;}finally{row.disabled=false;}},list,'conversation-history-item');if(item.preview)row.append(el('small','',item.preview.slice(0,180)));if(Number.isFinite(item.message_count))row.append(el('small','',item.message_count+' messages'));}
    const actions=el('div','dialog-actions');button('New side conversation',async()=>{await close();await create();},actions,'workspace-button');const done=button('Close',close,actions,'workspace-button');dialog.append(actions);layer.append(dialog);document.body.append(layer);
    layer.onkeydown=event=>{if(event.key==='Escape'){event.preventDefault();event.stopPropagation();close();}if(event.key==='Tab'){const all=[...dialog.querySelectorAll('button:not(:disabled)')],first=all[0],last=all.at(-1);if(event.shiftKey&&document.activeElement===first){event.preventDefault();last?.focus();}else if(!event.shiftKey&&document.activeElement===last){event.preventDefault();first?.focus();}}};await VisionShell.openSheet(layer,'.conversation-dialog');done.focus();
  }
  window.addEventListener('vision:conversations-changed',event=>{state=event.detail;render();});
  window.addEventListener('vision:history-loaded',()=>refresh().catch(error));
  window.addEventListener('vision:chat-state',event=>{state.busy=event.detail.busy;state.connected=event.detail.online;loading=event.detail.loading;render();});
  document.querySelector('#back').addEventListener('click',closeMenu);refresh().catch(error);render();
})();
