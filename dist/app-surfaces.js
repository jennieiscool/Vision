/* Live application frames are rendered in the panel; no native HWND covers the UI. */
(() => {
  const el=(tag,cls,text)=>{const n=document.createElement(tag);if(cls)n.className=cls;if(text!==undefined)n.textContent=text;return n;};
  const api=async(path,data)=>{const r=await fetch('/api/app-control/'+path,data===undefined?{}:{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)}),d=await r.json();if(!r.ok)throw Error(d.detail||'Application access failed.');return d;};
  const button=(label,action,parent)=>{const b=el('button','workspace-button',label);b.type='button';b.onclick=async()=>{b.disabled=true;try{await action();}catch(error){VisionWorkspace.notify(error);}finally{b.disabled=false;}};parent.append(b);return b;};
  let current=null;
  async function open(session){
    if(window.VisionEditor&&!await VisionEditor.mayLeave())return;
    const file={id:'application-'+session.id,name:session.name,kind:'native-app',appSession:session.id,workspaceId:session.workspace_id};
    VisionUI.addArtifact(file,false);VisionUI.choosePreview(file.id);
  }
  async function render(file,target){
    current?.dispose();if(file.workspaceId)VisionProjects.enterEdit();target.replaceChildren();target.className='workspace-file-view native-app-view';
    const bar=el('div','native-app-toolbar'),label=el('span','native-app-status','Finding application window…'),stage=el('div','native-app-stage');bar.append(label);target.append(bar,stage);
    stage.setAttribute('aria-label',file.name+' live application');
    let attempts=0,item,stream=null,video=null,disposed=false,timer=null,clickTimer=null,pointerStart=null,dragged=false,busy=false,geometry='',syncAgain=false,failed=false,captureStarting=false,lastTouch=0,queue=Promise.resolve();
    const alive=()=>!disposed&&target.isConnected&&VisionUI.currentPreview().id===file.id;
    const report=error=>{label.textContent=error.message;VisionWorkspace.notify(error);};
    const visible=()=>alive()&&!document.querySelector('#workspace').hidden&&!document.hidden&&![...document.querySelectorAll('.vision-modal-layer,.vision-settings-layer,.lock-screen,.profile-entry,.picker-list,.workspace-actions-menu,.workspace-context-menu')].some(layer=>!layer.hidden&&getComputedStyle(layer).display!=='none');
    const viewport=async(force=false)=>{
      if(!item?.hwnd||!alive())return;if(busy){syncAgain=true;return;}const r=stage.getBoundingClientRect(),show=visible()&&r.width>2&&r.height>2,rect=[r.left,r.top,r.width,r.height],key=JSON.stringify([show,...rect]);if(!force&&key===geometry)return;geometry=key;busy=true;
      try{item=await VisionDesktop.appViewport(file.appSession,{visible:show,rect});if(!alive())return;resume.hidden=!item.paused;label.textContent=item.reason||'Live application view';if(show&&!stream&&!captureStarting&&!failed)await capture();}catch(error){if(alive()){failed=true;label.textContent=error.message;}}finally{busy=false;if(syncAgain){syncAgain=false;viewport().catch(report);}}
    };
    const activity=()=>{if(Date.now()-lastTouch<1000)return;lastTouch=Date.now();api('sessions/'+file.appSession+'/control',{action:'takeover'}).then(result=>{item=result;resume.hidden=false;}).catch(report);};
    const manual=args=>{activity();queue=queue.catch(()=>{}).then(()=>api('manual/'+file.appSession,args)).then(result=>{if(result.error||result.ok===false)throw Error(result.error||result.message||'The application did not accept input.');}).catch(report);};
    const point=event=>{const r=video.getBoundingClientRect(),scale=Math.min(r.width/video.videoWidth,r.height/video.videoHeight),w=video.videoWidth*scale,h=video.videoHeight*scale,x=(event.clientX-r.left-(r.width-w)/2)/w,y=(event.clientY-r.top-(r.height-h)/2)/h;return x>=0&&x<=1&&y>=0&&y<=1?{x,y}:null;};
    async function capture(){
      captureStarting=true;
      try{const id=await VisionDesktop.appCapture(file.appSession),media=await navigator.mediaDevices.getUserMedia({audio:false,video:{mandatory:{chromeMediaSource:'desktop',chromeMediaSourceId:id,maxFrameRate:30}}});if(!alive()){media.getTracks().forEach(t=>t.stop());return;}stream=media;video=el('video','native-app-video');video.autoplay=true;video.muted=true;video.playsInline=true;video.tabIndex=0;video.setAttribute('aria-label',file.name+' interactive live view');video.srcObject=stream;stage.replaceChildren(video);await video.play();
        video.onpointerdown=event=>{if(event.button!==0)return;pointerStart=point(event);dragged=false;video.focus();video.setPointerCapture(event.pointerId);};
        video.onpointerup=event=>{const end=point(event);if(pointerStart&&end&&Math.hypot(end.x-pointerStart.x,end.y-pointerStart.y)>.01){dragged=true;clearTimeout(clickTimer);manual({action:'drag',from_x:pointerStart.x,from_y:pointerStart.y,...end});}pointerStart=null;};
        video.onclick=event=>{if(dragged){dragged=false;return;}const p=point(event);if(p){video.focus();clearTimeout(clickTimer);clickTimer=setTimeout(()=>manual({action:'click',...p}),220);}};
        video.ondblclick=event=>{clearTimeout(clickTimer);const p=point(event);if(p)manual({action:'double_click',...p});};
        video.oncontextmenu=event=>{event.preventDefault();const p=point(event);if(p)manual({action:'right_click',...p});};
        video.addEventListener('wheel',event=>{event.preventDefault();const p=point(event);if(p)manual({action:'scroll',...p,direction:event.deltaY<0?'up':'down',amount:Math.max(1,Math.min(10,Math.ceil(Math.abs(event.deltaY)/100)))});},{passive:false});
        video.onkeydown=event=>{if(event.isComposing||['Control','Shift','Alt','Meta'].includes(event.key))return;event.preventDefault();event.stopPropagation();const names={ArrowUp:'up',ArrowDown:'down',ArrowLeft:'left',ArrowRight:'right',' ':'space',Escape:'esc',Enter:'enter',Backspace:'backspace',Delete:'delete',Tab:'tab'};if(event.key.length===1&&!event.ctrlKey&&!event.altKey&&!event.metaKey)manual({action:'type',text:event.key});else manual({action:'key',keys:[event.ctrlKey?'ctrl':'',event.altKey?'alt':'',event.shiftKey?'shift':'',names[event.key]||event.key.toLowerCase()].filter(Boolean).join('+')});};
        video.oncompositionend=event=>{if(event.data)manual({action:'type',text:event.data});};
        label.textContent='Live application view · keyboard and mouse enabled';stream.getVideoTracks()[0].onended=()=>{if(alive()){stream=null;video?.remove();label.textContent='Live capture stopped. Reconnect to continue.';}};
      }catch(error){failed=true;label.textContent='Live view unavailable: '+error.message;}finally{captureStarting=false;}
    }
    if(file.workspaceId)button('Back to files',()=>VisionProjects.openById(file.workspaceId),bar);
    const takeover=button('Take control',async()=>{item=await api('sessions/'+file.appSession+'/control',{action:'takeover'});resume.hidden=false;label.textContent='You are in control · AI paused';},bar);
    const resume=button('Resume AI',async()=>{item=await api('sessions/'+file.appSession+'/control',{action:'resume'});resume.hidden=true;label.textContent='AI control resumed · application settings apply';},bar);resume.hidden=true;
    button('Allow next action',async()=>{await api('sessions/'+file.appSession+'/control',{action:'resume'});await api('sessions/'+file.appSession+'/control',{action:'allow-next'});resume.hidden=true;label.textContent='One AI action allowed';},bar);
    button('Reconnect',async()=>{failed=false;stream?.getTracks().forEach(t=>t.stop());stream=null;video?.remove();geometry='';if(!item?.hwnd){attempts=0;await find();}else await viewport(true);},bar);
    button('Close preview',async()=>{dispose();await api('sessions/'+file.appSession+'/control',{action:'detach'});VisionUI.closePreview(file.id);},bar);
    const resize=new ResizeObserver(()=>viewport().catch(report));resize.observe(stage);
    const observer=new MutationObserver(()=>viewport().catch(report));observer.observe(document.body,{subtree:true,attributes:true,attributeFilter:['hidden','class'],childList:true});
    const onVisibility=()=>viewport().catch(report);document.addEventListener('visibilitychange',onVisibility);window.addEventListener('resize',onVisibility);
    function dispose(){if(disposed)return;disposed=true;clearTimeout(timer);clearTimeout(clickTimer);resize.disconnect();observer.disconnect();document.removeEventListener('visibilitychange',onVisibility);window.removeEventListener('resize',onVisibility);stream?.getTracks().forEach(t=>t.stop());VisionDesktop.appViewport(file.appSession,{visible:false,rect:[0,0,1,1]}).catch(()=>{});if(current?.id===file.id)current=null;}
    current={id:file.id,dispose};
    async function find(){if(!alive())return;try{item=await api('sessions/'+file.appSession);if(!alive())return;if(item.hwnd){resume.hidden=!item.paused;stage.replaceChildren();await viewport(true);return;}stage.replaceChildren(el('p','native-app-message',item.reason));if(item.candidates?.length){for(const candidate of item.candidates)button(candidate.title,async()=>{item=await api('sessions/'+file.appSession+'/control',{action:'choose',hwnd:candidate.hwnd});await find();},stage);}else if(++attempts<30)timer=setTimeout(find,1000);else label.textContent='No application window was found. Use Reconnect after the app finishes opening.';}catch(error){if(alive())label.textContent=error.message;}}
    find();
  }
  window.addEventListener('vision:preview-selected',event=>{if(current&&event.detail.id!==current.id)current.dispose();});
  window.addEventListener('vision:workspace-refresh',()=>current?.dispose());
  window.VisionAppSurfaces={open,render};
})();
