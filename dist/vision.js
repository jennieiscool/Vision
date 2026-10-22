/* Presentation, panel sizing and real workspace previews. */
(() => {
  const $=s=>document.querySelector(s);
  // Rename prose branding while preserving usable paths, URLs and command/code snippets.
  const displayText=value=>String(value??'').split(/(`[^`]*`)/g).map((part,index)=>index%2?part:part.replace(/(?<![\w.\/\\-])Hermes(?![\w.\/\\-])/gi,'Vision')).join('');
  const words=$('#ring-words');
  let captionText='',consumed=0,queue=[],captionTimer=null,captionPaused=false,line=[],syncedIndex=-1;
  function nextWords(){
    captionTimer=null;
    if(captionPaused){captionTimer=setTimeout(nextWords,200);return;}
    if(!queue.length){words.replaceChildren();line=[];return;}
    const word=queue.shift();if(line.length>=2){line=[];words.replaceChildren();}line.push(word);
    const span=document.createElement('span');span.textContent=word;span.className='word-appear';words.append(span);
    captionTimer=setTimeout(nextWords,Math.max(530,word.length*65));
  }
  function captionReply(text,{reset=false,complete=false}={}){
    if(reset){clearTimeout(captionTimer);captionTimer=null;consumed=0;queue=[];line=[];captionText='';words.textContent='';}
    captionText=displayText(text).replace(/```[\s\S]*?(?:```|$)/g,' ').replace(/!?\[([^\]]+)\]\([^)]*\)/g,'$1').replace(/[*#_`>]/g,' ').trim();
    const tokens=captionText.split(/\s+/).filter(Boolean);
    // While streaming, leave the last potentially incomplete word for the next update.
    const available=complete?tokens.length:Math.max(0,tokens.length-1);
    while(available>consumed)queue.push(tokens[consumed++]);
    if(!captionTimer&&queue.length)nextWords();
  }
  function clearCaption(){clearTimeout(captionTimer);captionTimer=null;queue=[];line=[];syncedIndex=-1;words.replaceChildren();}
  function syncCaption({words:timedWords,position,active}){
    if(!active){clearCaption();return;}
    const index=timedWords.findIndex(word=>position>=word.start&&position<word.end);
    if(index===syncedIndex)return;
    syncedIndex=index;clearTimeout(captionTimer);captionTimer=null;words.replaceChildren();
    if(index<0)return;
    const first=Math.floor(index/2)*2;
    for(let i=first;i<=index;i++){const span=document.createElement('span');span.textContent=timedWords[i].word;if(i===index)span.className='spoken-word';words.append(span);}
  }

  function makeSplitter(name,orientation,handler){
    const rail=document.createElement('button');rail.type='button';rail.className='splitter '+orientation;
    rail.setAttribute('role','separator');rail.setAttribute('aria-orientation',orientation);rail.setAttribute('aria-label',name);rail.title=name+' · drag or use arrow keys';
    rail.setAttribute('aria-valuemin','0');rail.setAttribute('aria-valuemax','100');rail.setAttribute('aria-valuenow','50');
    let previous;
    rail.onpointerdown=event=>{previous=orientation==='vertical'?event.clientX:event.clientY;rail.setPointerCapture(event.pointerId);document.body.classList.add('resizing');event.preventDefault();};
    rail.onpointermove=event=>{if(!rail.hasPointerCapture(event.pointerId))return;const current=orientation==='vertical'?event.clientX:event.clientY;handler(current-previous);previous=current;};
    const end=()=>{document.body.classList.remove('resizing');saveLayout();};rail.onpointerup=end;rail.onlostpointercapture=end;
    rail.onkeydown=event=>{const keys=orientation==='vertical'?['ArrowLeft','ArrowRight']:['ArrowUp','ArrowDown'];if(keys.includes(event.key)){event.preventDefault();handler((keys.indexOf(event.key)?1:-1)*(event.shiftKey?40:12));saveLayout();}};
    return rail;
  }
  const root=document.documentElement,body=$('.workspace-body'),ws=$('#workspace');
  const size=name=>parseFloat(getComputedStyle(root).getPropertyValue('--'+name));
  const set=(name,value)=>root.style.setProperty('--'+name,Math.round(value)+'px');
  const clamp=(n,min,max)=>Math.max(min,Math.min(max,n));
  function saveLayout(){if(ws.classList.contains('editing'))return;try{localStorage.setItem('vision-layout',JSON.stringify({logs:size('logs-width'),chat:size('chat-width'),terminal:size('terminal-height')}));}catch{}}
  function constrain(){const available=Math.max(640,ws.clientWidth-36);if(!ws.classList.contains('editing'))set('logs-width',clamp(size('logs-width'),100,Math.max(100,available-size('chat-width')-204)));set('chat-width',clamp(size('chat-width'),240,Math.max(240,available-(ws.classList.contains('editing')?0:size('logs-width'))-204)));set('terminal-height',clamp(size('terminal-height'),90,Math.max(90,innerHeight-260)));}
  try{const saved=JSON.parse(localStorage.getItem('vision-layout'));if(saved)for(const [key,name] of [['logs','logs-width'],['chat','chat-width'],['terminal','terminal-height']])if(Number.isFinite(saved[key]))set(name,saved[key]);}catch{}
  const logRail=makeSplitter('Resize activity panel','vertical',delta=>{set('logs-width',clamp(size('logs-width')+delta,100,Math.max(100,ws.clientWidth-size('chat-width')-240)));});
  const chatRail=makeSplitter('Resize chat panel','vertical',delta=>{set('chat-width',clamp(size('chat-width')-delta,240,Math.max(240,ws.clientWidth-(ws.classList.contains('editing')?0:size('logs-width'))-240)));});
  $('.logs').after(logRail);$('.central-grid').after(chatRail);
  const terminalRail=makeSplitter('Resize terminal','horizontal',delta=>set('terminal-height',clamp(size('terminal-height')-delta,90,Math.max(90,innerHeight-260))));
  $('.terminals').before(terminalRail);window.addEventListener('resize',constrain);new MutationObserver(()=>{if(!ws.hidden)constrain();}).observe(ws,{attributes:true,attributeFilter:['hidden']});

  const central=$('.central-grid'),toolbar=document.createElement('div');toolbar.id='preview-toolbar';
  const select=document.createElement('select');select.id='preview-select';select.setAttribute('aria-label','Workspace preview');select.append(new Option('Golden grid','grid'));
  const download=document.createElement('a');download.id='preview-download';download.textContent='Download';download.hidden=true;download.download='';
  toolbar.append(select,download);central.prepend(toolbar);
  const view=document.createElement('div');view.id='artifact-view';view.hidden=true;$('#task-output').before(view);
  const artifacts=new Map();let current='grid',browserAvailable=false,taskAvailable=false,manualSelection=false,dismissed={};
  function choose(id){
    if(window.VisionEditor?.dirty)return;
    for(const media of view.querySelectorAll('video,audio')){media.pause();media.removeAttribute('src');media.load();}
    current=id;select.value=id;select.dispatchEvent(new Event('vision:selection-sync'));view.replaceChildren();
    window.dispatchEvent(new CustomEvent('vision:preview-selected',{detail:{id,file:artifacts.get(id)||null}}));view.hidden=true;$('#browser-view').hidden=id!=='browser';$('#task-output').hidden=id!=='task';download.hidden=true;
    if(!artifacts.has(id))return;
    const file=artifacts.get(id),url='/api/artifacts/'+encodeURIComponent(id)+'/file';view.hidden=false;download.href=url+'?download=1';download.download=file.name;download.hidden=['app-library','project','native-app'].includes(file.kind);
    if(window.VisionWorkspace){VisionWorkspace.render(file,view,url);return;}
    const type=file.media_type||'',extension=file.name.split('.').pop().toLowerCase();
    if(type.startsWith('image/')){const image=document.createElement('img');image.src=url;image.alt=file.name;view.append(image);}
    else if(['html','htm','pdf'].includes(extension)){const frame=document.createElement('iframe');frame.title=file.name;frame.setAttribute('sandbox','allow-scripts');frame.src=file.preview_url||url;view.append(frame);}
    else if(type.startsWith('audio/')||type.startsWith('video/')){const media=document.createElement(type.startsWith('audio/')?'audio':'video');media.controls=true;media.src=url;view.append(media);}
    else if(file.text){const pre=document.createElement('pre');pre.textContent='Loading…';view.append(pre);fetch(url).then(r=>{if(!r.ok)throw Error('Could not load preview');return r.text();}).then(text=>{if(current===id)pre.textContent=text;}).catch(e=>pre.textContent=e.message);}
    else{const wrap=document.createElement('p');wrap.textContent='Preview unavailable for this file. ';const link=document.createElement('a');link.href=url+'?download=1';link.download=file.name;link.textContent='Download '+file.name;wrap.append(link);view.append(wrap);}
  }
  select.onchange=async()=>{const requested=select.value;if(window.VisionEditor&&!await VisionEditor.mayLeave()){select.value=current;select.dispatchEvent(new Event('vision:selection-sync'));return;}manualSelection=true;choose(requested);};
  function addArtifact(file,activate=true){
    if(Object.hasOwn(dismissed,file.id)&&dismissed[file.id]===file.modified)return;
    const existing=artifacts.has(file.id);artifacts.set(file.id,file);
    if(!existing)select.append(new Option((file.kind==='computer'?'Computer · ':'')+file.name,file.id));
    if(activate)choose(file.id);
  }
  function browserFrame(payload){
    const firstFrame=!browserAvailable;if(firstFrame){if(!select.querySelector('option[value="browser"]'))select.append(new Option('Live browser','browser'));browserAvailable=true;}
    $('#browser-url').textContent=payload.url||'Browser';
    window.dispatchEvent(new CustomEvent('vision:browser-frame',{detail:{url:payload.url,width:payload.width||1280,height:payload.height||800}}));
    if(firstFrame&&!manualSelection&&['grid','task'].includes(current))choose('browser');
  }
  function taskOutput(text){if(!taskAvailable){select.append(new Option('Task output','task'));taskAvailable=true;}$('#task-output').textContent=displayText(text);if(!manualSelection&&['grid','task'].includes(current))choose('task');}
  async function copyText(text){
    try{await navigator.clipboard.writeText(text);}catch{const field=document.createElement('textarea');field.value=text;field.style.position='fixed';field.style.opacity='0';document.body.append(field);field.select();const okay=document.execCommand('copy');field.remove();if(!okay)throw Error('Select the text and press Ctrl+C to copy.');}
  }
  function closePreview(id){
    artifacts.delete(id);for(const option of [...select.options])if(option.value===id)option.remove();
    if(id==='browser')browserAvailable=false;if(id==='task')taskAvailable=false;
    if(current===id)choose('grid');select.dispatchEvent(new Event('vision:selection-sync'));
  }
  Object.assign(window.VisionUI ||= {},{choosePreview:id=>{manualSelection=true;choose(id);},closePreview,
    openedPreviews:()=>[...select.options].map(o=>o.value).filter(id=>id!=='grid'),
    previewFile:id=>artifacts.get(id)||null,
    currentPreview:()=>({id:current,file:artifacts.get(current)||null}),
    setDismissed:value=>{dismissed=value||{};},reopenPreview:id=>{delete dismissed[id];},
    resetPreviews:()=>{for(const id of [...artifacts.keys()])closePreview(id);},
    displayText,captionReply,browserFrame,taskOutput,addArtifact,copyText,syncCaption,pauseCaption:value=>{captionPaused=value;},clearCaption});
})();
