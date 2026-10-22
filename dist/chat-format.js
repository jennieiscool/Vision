/* Sanitized rich text shared by conversation, memory and skill readers. */
(() => {
  const strip=value=>String(value??'').replace(/\x1b\[[0-?]*[ -/]*[@-~]/g,'');
  function details(target,value,depth=0){
    target.classList.add('readable-details');
    if(value===null||value===undefined)return;
    if(typeof value==='string'){
      const text=strip(value);
      try{const parsed=JSON.parse(text);if(parsed&&typeof parsed==='object'){details(target,parsed,depth);return;}}catch{}
      const p=document.createElement('p');p.textContent=VisionUI.displayText(text).slice(0,6000);target.append(p);return;
    }
    if(typeof value!=='object'){const span=document.createElement('span');span.textContent=String(value);target.append(span);return;}
    if(Array.isArray(value)){const list=document.createElement('ul');for(const item of value.slice(0,40)){const li=document.createElement('li');details(li,item,depth+1);list.append(li);}target.append(list);return;}
    const dl=document.createElement('dl');
    for(const [key,item]of Object.entries(value).slice(0,40)){
      if(/token|password|secret|api_key|system_prompt/i.test(key)||item===null||item===undefined)continue;
      const dt=document.createElement('dt'),dd=document.createElement('dd');dt.textContent=key.replace(/[._-]/g,' ').replace(/^\w/,c=>c.toUpperCase());
      if(depth>=3&&typeof item==='object')dd.textContent=Array.isArray(item)?item.length+' items':'Details available in workspace';else details(dd,item,depth+1);
      dl.append(dt,dd);
    }
    target.append(dl);
  }
  function render(target,text,{links=true}={}){
    const clean=window.VisionUI?.displayText(strip(text))||strip(text);
    if(/^[\s]*[\[{]/.test(clean)){try{const value=JSON.parse(clean);if(value&&typeof value==='object'){target.replaceChildren();details(target,value);return;}}catch{}}
    target.innerHTML=DOMPurify.sanitize(marked.parse(clean,{gfm:true,breaks:true}),{FORBID_TAGS:['style','iframe','form','input','button','svg','video','audio'],FORBID_ATTR:['style'],ALLOW_DATA_ATTR:false});
    target.classList.add('rich-text');
    for(const table of target.querySelectorAll('table')){const wrap=document.createElement('div');wrap.className='table-scroll';table.replaceWith(wrap);wrap.append(table);}
    for(const image of target.querySelectorAll('img')){const source=image.getAttribute('src')||'';if(!/^https?:\/\//i.test(source)&&!source.startsWith('/api/'))image.remove();else{image.loading='lazy';image.referrerPolicy='no-referrer';}}
    for(const anchor of target.querySelectorAll('a')){
      let url;try{url=new URL(anchor.getAttribute('href'),location.origin);}catch{anchor.replaceWith(document.createTextNode(anchor.textContent));continue;}
      if(!['http:','https:'].includes(url.protocol)){anchor.replaceWith(document.createTextNode(anchor.textContent));continue;}
      anchor.removeAttribute('target');anchor.rel='noopener noreferrer';anchor.title=url.href;
      if(links){
        const bare=anchor.textContent===url.href||anchor.textContent===url.href.replace(/\/$/,'');
        if(bare){anchor.replaceChildren();anchor.className='link-card';const icon=document.createElement('span');icon.className='link-card-icon';icon.textContent='↗';const content=document.createElement('span'),name=document.createElement('strong'),path=document.createElement('small');name.textContent=url.hostname.replace(/^www\./,'');path.textContent=decodeURIComponent(url.pathname).replace(/[-_]/g,' ').slice(0,80)||'Open in workspace';content.append(name,path);anchor.append(icon,content);}
        anchor.onclick=event=>{event.preventDefault();window.VisionBrowser?.open(url.href);};
      }
    }
    for(const pre of target.querySelectorAll('pre')){const button=document.createElement('button');button.type='button';button.className='code-copy';button.textContent='Copy';button.onclick=async()=>{await VisionUI.copyText(pre.querySelector('code')?.textContent||pre.textContent);button.textContent='Copied';setTimeout(()=>button.textContent='Copy',1200);};pre.append(button);}
  }
  window.VisionRichText={render,strip,details};
})();
