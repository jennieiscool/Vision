/* The GUI speaks only to its own local Vision bridge. No model keys enter this file. */
(() => {
  const $ = s => document.querySelector(s);
  const messages = $('#messages'), chatEmpty = $('.chat-empty'), logFeed = $('#logs-feed');
  const input = $('#message'), sendButton = $('.composer button[type=submit]');
  const note = $('#chat-connection'), connection = $('.connection-state');
  const UI=window.VisionUI;
  let historyGeneration=0,loadingHistory=false,changingConversation=false,currentConversation='main',currentProfile='default';
  const drafts=new Map(),chatScroll=$('.chat-grid');let followLatest=true,pendingBottom=true,scrollFrame=0,settingScroll=false;
  function scrollLatest(force=false){if(!force&&!followLatest)return;if(force)followLatest=true;pendingBottom=true;if($('#workspace').hidden)return;cancelAnimationFrame(scrollFrame);settingScroll=true;scrollFrame=requestAnimationFrame(()=>{chatScroll.scrollTop=chatScroll.scrollHeight;pendingBottom=false;requestAnimationFrame(()=>{settingScroll=false;});});}
  chatScroll.addEventListener('scroll',()=>{if(!settingScroll&&!$('#workspace').hidden)followLatest=chatScroll.scrollHeight-chatScroll.clientHeight-chatScroll.scrollTop<80;},{passive:true});
  new MutationObserver(()=>{if(!$('#workspace').hidden&&pendingBottom)scrollLatest(true);}).observe($('#workspace'),{attributes:true,attributeFilter:['hidden']});
  new ResizeObserver(()=>{if(followLatest)scrollLatest();}).observe(messages);
  new ResizeObserver(()=>{if(followLatest)scrollLatest();}).observe(chatScroll);
  messages.addEventListener('load',()=>scrollLatest(),true);
  function stashDraft(){drafts.set(currentProfile+':'+currentConversation,{text:input.value,attachments:[...pendingAttachments]});}

  const logValue=(key,value)=>/token|password|secret|api_key|system_prompt/i.test(key)?'[hidden]':typeof value==='string'&&value.startsWith('data:image/')?'[Image in workspace preview]':typeof value==='string'&&value.length>12000?value.slice(0,12000)+'\n…':value;
  let pendingAttachments=[];
  const tray=document.createElement('div');tray.className='attachment-tray';tray.hidden=true;$('.composer').before(tray);
  const picker=document.createElement('input');picker.type='file';picker.multiple=true;picker.hidden=true;picker.setAttribute('aria-label','Choose files to attach');$('.composer').append(picker);
  const attach=document.createElement('button');attach.type='button';attach.id='attach-file';attach.textContent='+';attach.title='Attach images or files';attach.setAttribute('aria-label','Attach images or files');$('#message').before(attach);attach.onclick=()=>picker.click();
  function renderAttachments(){
    tray.replaceChildren();tray.hidden=!pendingAttachments.length;
    for(const file of pendingAttachments){const chip=document.createElement('div');chip.className='attachment-chip';if(file.media_type.startsWith('image/')){const img=document.createElement('img');img.src='/api/attachments/'+file.id;img.alt='';chip.append(img);}const name=document.createElement('span');name.textContent=file.name;const remove=document.createElement('button');remove.type='button';remove.textContent='×';remove.setAttribute('aria-label','Remove '+file.name);remove.onclick=()=>{pendingAttachments=pendingAttachments.filter(f=>f.id!==file.id);renderAttachments();};chip.append(name,remove);tray.append(chip);}
  }
  let uploading=0;
  async function uploadFiles(files){
    if(submitting)return;
    uploading++;attach.disabled=true;sendButton.disabled=true;
    try{for(const file of files){if(pendingAttachments.length>=10)throw Error('Attach up to 10 files per message.');const form=new FormData();form.append('file',file);const response=await fetch('/api/attachments',{method:'POST',body:form});const data=await response.json();if(!response.ok)throw Error(data.detail||'File upload failed');pendingAttachments.push(data);renderAttachments();}}
    catch(error){showError(error);}finally{uploading--;attach.disabled=uploading>0;sendButton.disabled=uploading>0||!online||busy;}
  }
  picker.onchange=()=>{uploadFiles(Array.from(picker.files));picker.value='';};
  input.addEventListener('paste',async event=>{const items=Array.from(event.clipboardData?.items||[]);const files=Array.from(event.clipboardData?.files||[]);for(const item of items){if(item.kind==='file'&&item.type.startsWith('image/')&&!files.some(f=>f.type===item.type)){const file=item.getAsFile();if(file)files.push(file);}}if(files.length){event.preventDefault();const pastedText=event.clipboardData.getData('text/plain');if(pastedText)input.setRangeText(pastedText,input.selectionStart,input.selectionEnd,'end');uploadFiles(files);}else if(!event.clipboardData?.getData('text/plain')&&window.VisionDesktop){event.preventDefault();const image=await VisionDesktop.pasteImage();if(image){const blob=await(await fetch(image)).blob();uploadFiles([new File([blob],'Clipboard image.png',{type:blob.type})]);}}});
  const conversation=$('.conversation');conversation.addEventListener('dragover',event=>{if(Array.from(event.dataTransfer.types).includes('Files')){event.preventDefault();conversation.classList.add('drag-over');}});
  conversation.addEventListener('dragleave',event=>{if(!conversation.contains(event.relatedTarget))conversation.classList.remove('drag-over');});
  conversation.addEventListener('drop',event=>{event.preventDefault();conversation.classList.remove('drag-over');if(event.dataTransfer.files.length)uploadFiles(Array.from(event.dataTransfer.files));});
  let online=false, busy=false, liveMessage=null, initialized=false, catalog=[], submitting=false;
  let eventSocket, voiceEnabled=true,micEnabled=false,wasSpeaking=false;
  const microphonePath='M12 3a3 3 0 0 1 3 3v6a3 3 0 0 1-6 0V6a3 3 0 0 1 3-3ZM5 10v2a7 7 0 0 0 14 0v-2M12 19v3M8 22h8';
  const menu=document.createElement('div');menu.id='command-menu';menu.hidden=true;$('.composer').append(menu);
  const stopAgent=document.createElement('button');stopAgent.id='stop-agent';stopAgent.type='button';stopAgent.textContent='Stop';stopAgent.hidden=true;stopAgent.setAttribute('aria-label','Stop current Vision task');stopAgent.title='Cancel the current Vision task';
  sendButton.before(stopAgent);
  stopAgent.onclick=()=>api('stop',{}).catch(showError);

  async function api(path,body){
    const response=await fetch('/api/'+path,body===undefined?{}:{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
    if(!response.ok){let detail;try{detail=(await response.json()).detail;}catch{}throw Error(typeof detail==='string'?detail:`Request failed (${response.status})`);}
    return response.json();
  }
  function showError(error){note.hidden=false;note.textContent=UI.displayText(error.message||String(error));note.classList.add('engine-error');if(voiceEnabled)$('#landing-voice-state').textContent=note.textContent;}
  VisionTerminals.onError(showError);
  window.addEventListener('vision:error',event=>showError(event.detail));
  function setStatus(connected,isBusy=busy){
    online=connected;busy=isBusy;connection.textContent=online?'Connected':'Offline';connection.classList.toggle('online',online);
    sendButton.disabled=loadingHistory||changingConversation||!online||(busy&&!input.value.trim().startsWith('/'));
    sendButton.setAttribute('aria-label','Send message');sendButton.title='Send message';
    stopAgent.hidden=!busy;
    note.classList.remove('engine-error');note.textContent=online?(busy?'Vision is working…':''):'Connecting…';note.hidden=!note.textContent;
    $('#model-select').disabled=!online||busy||loadingHistory||changingConversation;
    window.dispatchEvent(new CustomEvent('vision:chat-state',{detail:{online,busy,loading:loadingHistory||changingConversation}}));
  }
  const pendingRenders=new Set();let renderTimer;
  function renderStream(content){pendingRenders.add(content);if(renderTimer)return;renderTimer=setTimeout(()=>{renderTimer=null;for(const target of pendingRenders)if(target.isConnected)VisionRichText.render(target,target.dataset.raw);pendingRenders.clear();},90);}
  function appendMessage(role,text,attachments=[]){
    if(!text)return null;
    chatEmpty.hidden=true;
    const item=document.createElement('article');item.className='message '+role;
    const label=document.createElement('span');label.className='message-role';label.textContent=role==='assistant'?'Vision AI':role==='user'?'You':'System';
    const content=document.createElement('div');content.className='message-content';content.dataset.raw=String(text);VisionRichText.render(content,text);item.append(label,content);
    for(const file of attachments){const link=document.createElement('a');link.className='message-attachment';link.href=file.workspace?'/api/artifacts/'+file.id+'/file':'/api/attachments/'+file.id;link.download=file.name;link.textContent=file.name;if(file.media_type?.startsWith('image/')){const image=document.createElement('img');image.src=file.preview_image_url||link.href;image.alt=file.name;link.prepend(image);}item.append(link);}
    const copy=document.createElement('button');copy.type='button';copy.className='message-copy';copy.textContent='Copy';copy.setAttribute('aria-label','Copy message');copy.onclick=async()=>{try{await UI.copyText(content.dataset.raw||content.textContent);copy.textContent='Copied';setTimeout(()=>copy.textContent='Copy',1400);}catch(e){showError(e);}};item.append(copy);messages.append(item);
    scrollLatest();
    return content;
  }
  function logEvent(event){
    const {type,payload={}}=event;
    if(['heartbeat','browser.frame','message.delta','reasoning.delta','thinking.delta','session.info','artifact.available'].includes(type))return;
    const item=document.createElement('div');item.className='log-entry';
    const time=document.createElement('time');time.textContent=new Date((event.time||Date.now()/1000)*1000).toLocaleTimeString();
    const kind=document.createElement('span');kind.className='log-kind';kind.textContent=type;
    item.append(time,kind);
    const details=document.createElement('details'),summary=document.createElement('summary'),body=document.createElement('pre');
    summary.textContent=(payload.name||payload.summary||payload.text||payload.context||'Details').toString().slice(0,110);
    VisionRichText.details(body,payload);summary.textContent=UI.displayText(summary.textContent);details.append(summary,body);item.append(details);logFeed.append(item);
    while(logFeed.children.length>350)logFeed.firstChild.remove();logFeed.scrollTop=logFeed.scrollHeight;
  }
  function requestCard(type,payload){
    const panel=$('#pending-request');panel.hidden=false;panel.replaceChildren();
    const title=document.createElement('strong');title.textContent=type==='approval.request'?'Vision needs approval':'Vision needs your input';
    const text=document.createElement('p');text.textContent=payload.command||payload.question||payload.description||payload.prompt||payload.text||'Review the requested action.';
    panel.append(title,text);
    const method=type.replace('.request','.respond');
    const answer=async params=>{try{await api('respond',{method,params:{request_id:payload.request_id,...params}});panel.hidden=true;}catch(e){showError(e);}};
    if(type==='approval.request'){
      for(const [label,choice] of [['Allow once','once'],['Deny','deny']]){const b=document.createElement('button');b.textContent=label;b.onclick=()=>answer({choice});panel.append(b);}
    }else{
      const field=document.createElement('input');field.type=type==='sudo.request'||type==='secret.request'?'password':'text';field.setAttribute('aria-label','Response to Vision');panel.append(field);
      const b=document.createElement('button');b.textContent='Respond';b.onclick=()=>answer({[type==='sudo.request'?'password':type==='secret.request'?'value':'answer']:field.value});panel.append(b);
    }
  }
  function handleEvent(event){
    const p=event.payload||{},type=event.type;
    if(type==='heartbeat')return;
    if(type==='workspace.context'){window.dispatchEvent(new CustomEvent('vision:workspace-context',{detail:p}));return;}
    if(type==='workspace.notice'){appendMessage('system',p.text);return;}
    if(type==='browser.frame'||type==='browser.state'){UI.browserFrame(p);return;}
    if(type==='artifact.available'){UI.addArtifact(p);return;}
    logEvent(event);
    if(type==='bridge.ready'){setStatus(true,false);initialize().catch(showError);}
    if(type==='bridge.error'){setStatus(false,false);showError(Error(p.text));}
    if(type==='conversation.changed'){window.dispatchEvent(new CustomEvent('vision:conversations-changed',{detail:p}));return;}
    if(type==='chat.reloaded'){initialized=false;initialize({conversationOnly:!!p.conversation_only}).catch(showError);if(!p.conversation_only)window.dispatchEvent(new Event('vision:workspace-refresh'));}
    if(type==='user.message'){followLatest=true;liveMessage=null;UI.captionReply('',{reset:true});appendMessage('user',p.text,p.attachments||[]);setStatus(true,true);}
    if(type==='message.start')UI.captionReply('',{reset:true});
    if(type==='message.delta'){
      if(!liveMessage)liveMessage=appendMessage('assistant',p.text);else{liveMessage.dataset.raw=(liveMessage.dataset.raw||'')+(p.text||'');renderStream(liveMessage);}
      if(!voiceEnabled)UI.captionReply(liveMessage?.dataset.raw||'');
      scrollLatest();
    }
    if(type==='message.complete'){
      if(liveMessage){if(p.text){liveMessage.dataset.raw=p.text;VisionRichText.render(liveMessage,p.text);}}else if(p.text)appendMessage('assistant',p.text);
      const text=p.text||liveMessage?.dataset.raw||'';liveMessage=null;setStatus(online,false);
      if(text&&!voiceEnabled)UI.captionReply(text,{complete:true});
      if(p.status==='interrupted'&&!text)appendMessage('system','Vision was stopped before a reply was returned.');
      if(voiceEnabled&&text&&!['error','interrupted'].includes(p.status)){UI.clearCaption();speak(text);}
    }
    if(type==='settings.saved')appendMessage('system',p.text);
    if(type==='command.output'){appendMessage('system',[p.warning,p.text].filter(Boolean).join('\n'));refreshModel().catch(()=>{});}
    if(type==='tool.start'||type==='tool.progress'){$('#activity-bar').hidden=false;$('#activity-bar').textContent=(p.name||'Vision')+(p.context?' · '+p.context:'');}
    if(type==='tool.complete'){
      $('#activity-bar').hidden=false;$('#activity-bar').textContent=p.summary||p.name||'Task complete';
      if(!String(p.name).startsWith('browser'))UI.taskOutput(typeof p.result==='string'?p.result:JSON.stringify(p.result??p.summary??'',logValue,2));
    }
    if(type.endsWith('.request'))requestCard(type,p);
    if(type==='request.resolved'||type.endsWith('.expire'))$('#pending-request').hidden=true;
  }
  async function initialize({conversationOnly=false}={}){
    if(initialized)return;
    const generation=++historyGeneration;loadingHistory=true;input.disabled=true;
    try{
      const status=await api('status');if(generation!==historyGeneration)return;setStatus(status.connected,status.busy);
      if(!status.connected){if(status.error)showError(Error(status.error));return;}
      initialized=true;
      const history=await api('history');if(generation!==historyGeneration)return;
      const nextConversation=history.conversation||'main',nextProfile=history.profile||'default';
      if(nextConversation!==currentConversation||nextProfile!==currentProfile){stashDraft();currentConversation=nextConversation;currentProfile=nextProfile;const draft=drafts.get(currentProfile+':'+currentConversation);input.value=draft?.text||'';pendingAttachments=draft?.attachments||[];renderAttachments();}
      followLatest=true;messages.replaceChildren();chatEmpty.hidden=false;liveMessage=null;$('#pending-request').hidden=true;
      for(const message of history.messages||[])if(['user','assistant'].includes(message.role))appendMessage(message.role,message.text||message.content,message.attachments||[]);
      UI.captionReply(history.busy?history.stream||'':'',{reset:true});
      if(history.stream)liveMessage=appendMessage('assistant',history.stream);
      setStatus(true,history.busy);logFeed.replaceChildren();for(const event of history.logs||[]){logEvent(event);if(event.type==='settings.saved')appendMessage('system',event.payload?.text);}
      for(const request of history.requests||[])requestCard(request.type,request.payload);
      const commands=await api('commands');if(generation!==historyGeneration)return;catalog=commands.all||commands.commands||commands.pairs||[];
      if(!Array.isArray(catalog))catalog=[];
      if(!catalog.length&&commands.categories)catalog=commands.categories.flatMap(c=>c.commands||c.items||[]);
      await refreshModel();if(generation!==historyGeneration)return;
      if(!conversationOnly){const previews=await api('artifacts');if(generation!==historyGeneration)return;UI.setDismissed(previews.dismissed);UI.resetPreviews();for(const file of previews.files||[])UI.addArtifact(file,false);}
      scrollLatest(true);window.dispatchEvent(new CustomEvent('vision:history-loaded',{detail:{conversation:currentConversation,profile:currentProfile}}));
    }catch(e){if(generation===historyGeneration)initialized=false;throw e;}
    finally{if(generation===historyGeneration){loadingHistory=false;input.disabled=changingConversation;setStatus(online,busy);}}
  }
  async function refreshModel(){
    const data=await api('models');const select=$('#model-select');select.replaceChildren();
    const current=new Option(data.current||'Configure Vision with /model','');select.append(current);
    select.append(new Option('Choose provider / model…','configure'));
    select.disabled=!online||busy||loadingHistory||changingConversation;
  }
  $('#model-select').onchange=event=>{if(event.target.value==='configure')terminalConnect('model');event.target.selectedIndex=0;};
  async function connect(){
    try{await fetch('/',{cache:'no-store'});}catch{}
    const protocol=location.protocol==='https:'?'wss:':'ws:';
    eventSocket=new WebSocket(protocol+'//'+location.host+'/api/events');
    eventSocket.onopen=()=>initialize().catch(showError);
    eventSocket.onmessage=event=>{try{const frame=JSON.parse(event.data);if(frame.type==='bridge.status'){setStatus(frame.payload.connected,frame.payload.busy);if(frame.payload.error)showError(Error(frame.payload.error));}else handleEvent(frame);}catch(e){showError(e);}};
    eventSocket.onclose=()=>{setStatus(false,false);initialized=false;setTimeout(connect,3000);};
    eventSocket.onerror=()=>{};
  }
  async function submit(){
    if(submitting||uploading||loadingHistory||changingConversation)return;
    menu.hidden=true;
    const text=input.value.trim();
    if(/^\/model\s*$/i.test(text)){terminalConnect('model');input.value='';return;}
    if(busy&&!text.startsWith('/')){showError(Error('Vision is still working. Use the separate Stop button only if you want to cancel.'));return;}
    if((!text&&!pendingAttachments.length)||!online)return;
    if(text.startsWith('/')&&pendingAttachments.length){showError(Error('Send attachments with a message, then run the slash command separately.'));return;}
    if(/^\/voice(?:\s|$)/i.test(text)){
      const action=text.split(/\s+/)[1]?.toLowerCase();
      if(action==='status')appendMessage('system',voiceEnabled?'Voice playback is enabled.':'Kokoro voice is muted.');
      else if(action==='off'){await muteVoice();}
      else if(action==='on'){if(!voiceEnabled)await enableVoice();}
      else if(!action){if(voiceEnabled)await muteVoice();else await enableVoice();}
      else appendMessage('system','Use /voice on, /voice off, or /voice status. Speech uses the configured Kokoro blend.');
      input.value='';return;
    }
    submitting=true;input.disabled=true;
    try{await api(text.startsWith('/')?'command':'chat',text.startsWith('/')?{command:text}:{text,attachments:pendingAttachments.map(f=>f.id)});input.value='';pendingAttachments=[];renderAttachments();}
    catch(e){showError(e);}finally{submitting=false;input.disabled=false;input.focus();sendButton.disabled=loadingHistory||changingConversation||!online||(busy&&!input.value.trim().startsWith('/'));}
  }
  $('.composer').addEventListener('submit',event=>{event.preventDefault();submit().catch(showError);});
  input.addEventListener('keydown',event=>{
    if(event.key==='Escape'){menu.hidden=true;return;}
    if(event.key==='Enter'&&!event.shiftKey){event.preventDefault();if(!event.repeat)submit().catch(showError);}
  });
  input.addEventListener('input',()=>{
    sendButton.disabled=loadingHistory||changingConversation||!online||(busy&&!input.value.trim().startsWith('/'));
    const text=input.value;menu.replaceChildren();
    if(!text.startsWith('/')||text.includes(' ')){menu.hidden=true;return;}
    const query=text.toLowerCase();
    const matches=catalog.map(c=>Array.isArray(c)?{name:c[0],description:c[1]}:c).filter(c=>String(c.name||c.command||'').toLowerCase().startsWith(query));
    for(const c of matches){const b=document.createElement('button');b.type='button';const strong=document.createElement('strong'),desc=document.createElement('span');strong.textContent=c.name||c.command;desc.textContent=c.description||'';b.append(strong,desc);b.onclick=()=>{input.value=strong.textContent+' ';menu.hidden=true;input.focus();};menu.append(b);}
    menu.hidden=!matches.length;
  });

  function terminalConnect(mode='shell'){
    VisionTerminals.open(mode);
  }

  function voiceStatus(text,state={}){
    let status=text;
    if(state.speaking&&(text==='Microphone muted'||text==='Listening'||text==='Speech enabled'))status=state.paused?'Speech paused':'Vision is speaking';
    if(state.speaking&&!micEnabled)status+=' / Mic muted';
    if(!voiceEnabled&&text!=='Speech muted')status+=' / Speaker muted';
    $('#voice-state').textContent=status;$('#landing-voice-state').textContent=status;
  }
  function updateVoice(){
    for(const button of document.querySelectorAll('.voice-toggle')){button.setAttribute('aria-pressed',String(micEnabled));button.setAttribute('aria-label',micEnabled?'Mute microphone':'Unmute microphone');button.title=micEnabled?'Mute microphone':'Unmute microphone';button.querySelector('path').setAttribute('d',microphonePath+(micEnabled?'':'M3 3l18 18'));}
    for(const button of document.querySelectorAll('.output-toggle')){button.setAttribute('aria-pressed',String(voiceEnabled));button.title=voiceEnabled?'Mute speaker':'Unmute speaker';button.setAttribute('aria-label',button.title);button.querySelector('path').setAttribute('d','M11 5 6 9H3v6h3l5 4V5M15 8a6 6 0 0 1 0 8'+(voiceEnabled?'M18 5a10 10 0 0 1 0 14':'M3 3l18 18'));}
    voiceStatus(micEnabled?'Listening':'Microphone muted',{speaking:typeof voiceController!=='undefined'&&voiceController.speaking,paused:typeof voiceController!=='undefined'&&voiceController.paused});
  }
  const voiceController=new VisionVoice({
    connected:()=>online,canListen:()=>online&&!busy&&!loadingHistory&&!changingConversation,
    status:voiceStatus,error:showError,
    enabled:value=>{micEnabled=value;updateVoice();},
    outputEnabled:value=>{voiceEnabled=value;updateVoice();},
    level:value=>{$('#microphone-level').value=value;},
    captions:payload=>UI.syncCaption(payload),
    playback:({active,paused})=>{
      UI.pauseCaption(active&&paused);
      if(wasSpeaking&&!active)UI.clearCaption();wasSpeaking=active;
      for(const button of document.querySelectorAll('.speech-pause')){
        button.hidden=!active;button.disabled=!active;button.setAttribute('aria-label',paused?'Resume spoken reply':'Pause spoken reply');
        button.title=paused?'Resume spoken reply':'Pause spoken reply';button.setAttribute('aria-pressed',String(paused));
        button.querySelector('path').setAttribute('d',paused?'m8 5 11 7-11 7z':'M9 6v12M15 6v12');
      }
    },
    transcript:async text=>{if(loadingHistory||changingConversation)return;await api(text.startsWith('/')?'command':'chat',text.startsWith('/')?{command:text}:{text});}
  });
  const muteVoice=()=>voiceController.setOutputEnabled(false);
  const enableVoice=()=>voiceController.setOutputEnabled(true);
  const speak=text=>voiceController.speak(text).catch(showError);
  $('.speech-pause').hidden=true;
  const workspacePause=$('.speech-pause').cloneNode(true);
  $('#workspace-voice').before(workspacePause);
  document.querySelectorAll('.speech-pause').forEach(button=>button.addEventListener('click',()=>{
    if(voiceController.paused)voiceController.resumePlayback().catch(showError);else voiceController.pausePlayback();
  }));
  $('#microphone-select').onchange=()=>{if(micEnabled)voiceController.unmute($('#microphone-select').value||undefined);};
  document.querySelectorAll('.voice-toggle').forEach(button=>button.addEventListener('click',()=>micEnabled?voiceController.mute():voiceController.unmute($('#microphone-select').value||undefined)));
  window.addEventListener('beforeunload',()=>{voiceController.close();eventSocket?.close();});
  for(const parent of [document.querySelector('.controls'),document.querySelector('.workspace-header')]){
    const output=document.createElement('button');output.className='output-toggle';output.innerHTML='<svg viewBox="0 0 24 24" aria-hidden="true"><path/></svg>';output.onclick=()=>voiceController.setOutputEnabled(!voiceEnabled).catch(showError);parent.append(output);
  }
  document.addEventListener('pointerdown',()=>voiceController.unlockAudio().catch(showError),{once:true});
  navigator.mediaDevices?.addEventListener('devicechange',()=>voiceController.updateDevices().catch(showError));
  voiceController.refreshDevices().catch(()=>voiceController.updateDevices().catch(showError));
  window.VisionChat={attach:uploadFiles};
  Object.assign(window.VisionChat ||= {},{
    prepareSwitch:()=>{if(submitting||uploading)throw Error('Wait for the message or attachment to finish sending.');stashDraft();changingConversation=true;voiceController.resetConversation();UI.clearCaption();menu.hidden=true;input.disabled=true;setStatus(online,busy);},
    finishSwitch:()=>{changingConversation=false;input.disabled=loadingHistory;setStatus(online,busy);},
    reload:async()=>{initialized=false;await initialize({conversationOnly:true});},
    scrollToLatest:()=>scrollLatest(true)
  });
  window.VisionAudio={controller:voiceController,refresh:()=>voiceController.refreshDevices(),select:async id=>{$('#microphone-select').value=id;voiceController.deviceId=id;if(micEnabled)await voiceController.unmute(id||undefined);}};
  window.addEventListener('vision:refresh-history',()=>{initialized=false;initialize().catch(showError);});
  setStatus(false,false);updateVoice();
  if(['localhost','127.0.0.1'].includes(location.hostname)&&location.port==='8787'){
    connect();setInterval(()=>{if(!initialized)initialize().catch(showError);},4000);
  }else{note.textContent='Open the Vision desktop app to use Vision.';$('#model-select').replaceChildren(new Option('Desktop app required',''));}
})();
