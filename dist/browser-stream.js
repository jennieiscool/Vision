/* Latest-frame video transport, separate from chat/log events. Audio plays locally in Chromium. */
(() => {
  const surface=document.querySelector('#browser-image'),view=document.querySelector('#browser-view'),workspace=document.querySelector('#workspace');
  const context=surface.getContext('2d',{alpha:false,desynchronized:true});
  let socket=null,reconnect=null,pending=null,decoding=false,bitmap=null,generation=0;
  function visible(){return !document.hidden&&!workspace.hidden&&!view.hidden;}
  function draw(){
    if(!bitmap||!visible())return;
    const rect=surface.getBoundingClientRect(),dpr=Math.min(devicePixelRatio||1,2);
    if(rect.width<1||rect.height<1)return;
    const width=Math.round(rect.width*dpr),height=Math.round(rect.height*dpr);
    if(surface.width!==width||surface.height!==height){surface.width=width;surface.height=height;}
    context.fillStyle='#050503';context.fillRect(0,0,width,height);
    const ratio=Math.min(width/bitmap.width,height/bitmap.height);
    context.drawImage(bitmap,(width-bitmap.width*ratio)/2,0,bitmap.width*ratio,bitmap.height*ratio);
  }
  async function decode(){
    if(decoding)return;decoding=true;
    try{
      while(pending){
        const packet=pending;pending=null;
        const token=generation,next=await createImageBitmap(new Blob([packet],{type:'image/jpeg'}));
        if(token!==generation||!visible()){next.close();continue;}
        bitmap?.close();bitmap=next;draw();
      }
    }catch(error){window.dispatchEvent(new CustomEvent('vision:error',{detail:Error('Browser preview could not decode a frame. Reconnecting…')}));socket?.close();}
    finally{decoding=false;}
  }
  function update(){
    clearTimeout(reconnect);
    if(!visible()){
      generation++;pending=null;
      if(socket){const previous=socket;socket=null;previous.close();}
      return;
    }
    if(socket&&socket.readyState<2)return;
    const connection=new WebSocket((location.protocol==='https:'?'wss:':'ws:')+'//'+location.host+'/api/browser/stream');
    socket=connection;connection.binaryType='arraybuffer';
    connection.onmessage=event=>{
      if(socket!==connection)return;
      if(typeof event.data==='string'){try{VisionUI.browserFrame(JSON.parse(event.data));}catch{}return;}
      pending=event.data;decode();
    };
    connection.onclose=()=>{if(socket===connection){socket=null;if(visible())reconnect=setTimeout(update,1000);}};
    connection.onerror=()=>{};
  }
  const observer=new MutationObserver(update);observer.observe(workspace,{attributes:true,attributeFilter:['hidden']});observer.observe(view,{attributes:true,attributeFilter:['hidden']});
  new ResizeObserver(draw).observe(surface);document.addEventListener('visibilitychange',update);
  window.addEventListener('beforeunload',()=>{clearTimeout(reconnect);generation++;socket?.close();bitmap?.close();});
  update();
})();
