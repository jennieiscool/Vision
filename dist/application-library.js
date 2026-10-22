/* An application preview is file identity and scan state, never an automatic launch. */
(() => {
  const el=(tag,cls,text)=>{const n=document.createElement(tag);if(cls)n.className=cls;if(text!==undefined)n.textContent=text;return n;};
  const api=async(path,data)=>{const r=await fetch('/api/'+path,data===undefined?{}:{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)});const d=await r.json();if(!r.ok)throw Error(d.detail||'Application action failed.');return d;};
  let selected='',activeDialog=null;
  const button=(label,action,parent)=>{const n=el('button','workspace-button',label);n.type='button';n.onclick=async()=>{n.disabled=true;try{await action();}catch(error){VisionWorkspace.notify(error);}finally{n.disabled=false;}};parent.append(n);return n;};
  async function show(){
    if(activeDialog){render(activeDialog.body);activeDialog.close.focus();return;}
    const layer=el('div','vision-modal-layer'),dialog=el('section','vision-dialog workspace-app-dialog'),header=el('header','workspace-app-dialog-header'),heading=el('h2','','Applications'),body=el('div','workspace-app-dialog-body');heading.id='vision-app-library-title';dialog.setAttribute('role','dialog');dialog.setAttribute('aria-modal','true');dialog.setAttribute('aria-labelledby',heading.id);header.append(heading);
    let closing=false;const previous=document.activeElement;
    const close=button('×',async()=>{if(closing)return;closing=true;await VisionShell.closeSheet(layer,'.workspace-app-dialog');layer.remove();activeDialog=null;if(previous?.isConnected)previous.focus();},header);close.classList.add('workspace-app-dialog-close');close.title='Close applications';close.setAttribute('aria-label','Close applications');
    dialog.append(header,body);layer.append(dialog);document.body.append(layer);activeDialog={layer,body,close};render(body);
    layer.addEventListener('keydown',event=>{if(event.key==='Escape'){event.preventDefault();event.stopPropagation();close.click();}if(event.key==='Tab'){const buttons=[...dialog.querySelectorAll('button:not(:disabled)')],first=buttons[0],last=buttons.at(-1);if(event.shiftKey&&document.activeElement===first){event.preventDefault();last?.focus();}else if(!event.shiftKey&&document.activeElement===last){event.preventDefault();first?.focus();}}});
    dialog.addEventListener('dragover',event=>{if([...event.dataTransfer.types].includes('Files')){event.preventDefault();dialog.classList.add('app-drop-active');}});dialog.addEventListener('dragleave',event=>{if(!dialog.contains(event.relatedTarget))dialog.classList.remove('app-drop-active');});
    dialog.addEventListener('drop',async event=>{event.preventDefault();dialog.classList.remove('app-drop-active');for(const file of event.dataTransfer.files){try{const path=window.VisionDesktop?.filePath(file);if(path)await addPath(path);else await upload(file);}catch(error){VisionWorkspace.notify(error);}}});
    await VisionShell.openSheet(layer,'.workspace-app-dialog');if(!closing)close.focus();
  }
  async function addPath(path){const item=await api('app-library/open',{path});selected=item.id;await show();}
  async function upload(file){const form=new FormData();form.append('file',file);const r=await fetch('/api/app-library/upload',{method:'POST',body:form}),data=await r.json();if(!r.ok)throw Error(data.detail||'The app could not be added.');selected=data.id;await show();}
  function render(target){
    const host=el('section','workspace-app-library'),heading=el('div','workspace-library-heading');button('Add application',async()=>{if(!window.VisionDesktop?.pickFiles)throw Error('Drop an application file here to add it.');for(const path of await VisionDesktop.pickFiles())await addPath(path);},heading);host.append(heading,el('p','workspace-library-note','Open applications as interactive live views in the grid. Defender scan results reduce risk; no scan guarantees safety.'));const list=el('div','workspace-app-list');host.append(list);target.replaceChildren(host);
    let loading=false,timer,pending=false;const alive=()=>host.isConnected&&!target.hidden;
    async function refresh(){if(!alive()||loading)return;clearTimeout(timer);loading=true;try{const data=await api('app-library');if(!alive())return;pending=data.items.some(item=>item.state==='scanning');list.replaceChildren();if(!data.items.length)list.append(el('p','workspace-preview-note','Add or drop an .exe application, .msi installer or Windows .lnk shortcut.'));
      for(const item of [...data.items].reverse()){
        const card=el('article','workspace-app-card'+(item.id===selected?' selected':''));card.append(el('h3','',item.name));const labels={scanning:'Scanning…',clear:'No threat detected',blocked:'Blocked — detection or scan error',unavailable:'Scan unavailable'};card.append(el('span','workspace-app-state '+item.state,labels[item.state]||'Scan required'),el('p','workspace-app-detail',item.detail||''));
        const details=el('dl','workspace-app-details');for(const [name,value] of [...(item.shortcut?[['Shortcut target',item.target_path||item.target_name],['Arguments',item.argument_text||'None']]:[]),['Publisher',item.publisher||'Not verified'],['Signature',item.signature||'Pending'],['Scanned',item.scanned_at?new Date(item.scanned_at).toLocaleString():'Pending'],['Definitions',item.version||'Unavailable'],['SHA-256',item.sha256||'Pending']]){details.append(el('dt','',name),el('dd','',value));}card.append(details);
        const actions=el('div','workspace-app-actions');const open=button('Open',async()=>{if(!window.VisionDesktop?.launchApp)throw Error('Use the Vision desktop app to launch applications.');const result=await VisionDesktop.launchApp(item.id);await VisionAppSurfaces.open(result);activeDialog?.close.click();},actions);open.disabled=item.state!=='clear'||!window.VisionDesktop?.launchApp;open.title=open.disabled?'A successful scan and the desktop app are required.':'Open in Vision preview';
        const scan=button('Scan again',async()=>{await api('app-library/'+item.id+'/scan',{});await refresh();},actions);scan.disabled=item.state==='scanning';button('Remove',async()=>{await api('app-library/'+item.id+'/remove',{});await refresh();},actions);card.append(actions);list.append(card);
      }
    }catch(error){if(alive())VisionWorkspace.notify(error);}finally{loading=false;if(alive()&&pending){clearTimeout(timer);timer=setTimeout(refresh,2500);}}}
    refresh();
  }
  window.VisionApps={show,addPath,upload,render};
})();
