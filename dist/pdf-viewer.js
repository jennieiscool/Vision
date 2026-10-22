/* Local PDF page rendering works without a browser plugin or active PDF scripts. */
(() => {
  const el=(tag,cls,text)=>{const n=document.createElement(tag);if(cls)n.className=cls;if(text!==undefined)n.textContent=text;return n;};
  async function create(file,target,metadata=null,valid=()=>true){
    const info=metadata||await fetch('/api/pdf/'+file.id).then(async r=>{const data=await r.json();if(!r.ok)throw Error(data.detail);return data;});
    if(!valid())return null;
    const host=el('div','workspace-pdf-viewer'),tools=el('div','workspace-sheet-tools'),stage=el('div','workspace-pdf-stage'),image=el('img','workspace-pdf-page'),text=el('pre','workspace-pdf-text'),label=el('span','workspace-page-label');image.alt='PDF page';image.draggable=false;text.hidden=true;let page=0,rotation=0,zoom=1;
    const button=(name,action)=>{const b=el('button','workspace-button',name);b.type='button';b.onclick=()=>Promise.resolve().then(action).catch(VisionWorkspace.notify);tools.append(b);return b;};
    const prev=button('Previous',()=>go(page-1)),next=button('Next',()=>go(page+1));button('−',()=>resize(Math.max(.4,zoom-.2)));button('Fit',()=>resize(1));button('+',()=>resize(Math.min(3,zoom+.2)));button('Page text',async()=>{text.hidden=!text.hidden;if(!text.hidden){const response=await fetch('/api/pdf/'+file.id+'/text?page='+page),data=await response.json();if(!response.ok)throw Error(data.detail);text.textContent=data.text||'No text layer on this page. The original PDF is available to Vision.';}});tools.append(label);stage.append(image,text);host.append(tools,stage);target.append(host);
    function resize(value){zoom=value;image.style.width=zoom===1?'':(zoom*100)+'%';image.style.maxWidth=zoom>1?'none':'';}
    function draw(){prev.disabled=page===0;next.disabled=page>=info.pages.length-1;label.textContent='Page '+(page+1)+' of '+info.pages.length;image.alt=file.name+' — page '+(page+1);image.src='/api/pdf/'+file.id+'/page?page='+page+'&rotation='+rotation+'&width='+(zoom>1?2400:1400);text.hidden=true;}
    function go(index){page=Math.max(0,Math.min(info.pages.length-1,Number(index)));draw();host.dispatchEvent(new CustomEvent('vision:pdf-page',{bubbles:true,detail:{page}}));}
    image.onerror=()=>{if(host.isConnected)VisionWorkspace.notify(Error('The PDF page could not render. Check whether the file moved or is encrypted.'));};draw();return {go,rotate:value=>{rotation=value;draw();},element:host};
  }
  window.VisionPDFViewer={create};
})();
