/* Each terminal tab owns one real PTY, socket and xterm instance. */
(() => {
  const host=document.querySelector('#terminal-container'),tabs=document.createElement('div');tabs.id='terminal-tabs';tabs.setAttribute('role','tablist');tabs.setAttribute('aria-label','Terminals');host.before(tabs);
  const create=document.querySelector('#terminal-connect');create.textContent='+ New terminal';create.title='Open a new terminal';
  document.querySelector('#terminal-close').remove();
  let active=null,counter=0,error=()=>{};const sessions=new Map();
  function resize(item){if(!item||item!==active||document.querySelector('#workspace').hidden)return;try{item.fit.fit();if(item.socket?.readyState===1)item.socket.send(JSON.stringify({type:'resize',cols:item.term.cols,rows:item.term.rows}));}catch{}}
  function activate(item,focus=true){
    active=item;for(const session of sessions.values()){session.panel.hidden=session!==item;session.tab.setAttribute('aria-selected',String(session===item));session.tab.tabIndex=session===item?0:-1;}
    requestAnimationFrame(()=>{resize(item);if(focus)item?.term.focus();});
  }
  function close(item){
    const index=[...sessions.keys()].indexOf(item.id);item.socket?.close();item.term.dispose();item.panel.remove();item.wrapper.remove();sessions.delete(item.id);
    if(active===item){const remaining=[...sessions.values()];activate(remaining[Math.min(index,remaining.length-1)]||null,false);}
  }
  function open(mode='shell'){
    if(sessions.size>=8){error(Error('You can open up to eight terminal tabs. Close a tab to create another.'));return;}
    if(mode==='model'){const existing=[...sessions.values()].find(s=>s.mode==='model'&&s.socket?.readyState<2);if(existing){activate(existing);return;}}
    const id=++counter,panel=document.createElement('div');panel.id='terminal-panel-'+id;panel.className='terminal-session';panel.setAttribute('role','tabpanel');panel.setAttribute('aria-labelledby','terminal-tab-'+id);host.append(panel);
    const wrapper=document.createElement('div');wrapper.className='terminal-tab';const tab=document.createElement('button');tab.id='terminal-tab-'+id;tab.type='button';tab.setAttribute('role','tab');tab.setAttribute('aria-controls',panel.id);tab.textContent=mode==='model'?'Model setup':'Terminal '+id;
    const remove=document.createElement('button');remove.type='button';remove.className='terminal-tab-close';remove.textContent='×';remove.setAttribute('aria-label','Close '+tab.textContent);wrapper.append(tab,remove);tabs.append(wrapper);
    const term=new Terminal({fontFamily:'Consolas, monospace',fontSize:13,cursorBlink:true,theme:{background:'#0b0905',foreground:'#eddbb3',cursor:'#f3cf78',selectionBackground:'#b58c4677'},scrollback:5000});
    const fit=new FitAddon.FitAddon();term.loadAddon(fit);term.open(panel);
    const item={id,panel,wrapper,tab,term,fit,mode,socket:null};sessions.set(id,item);tab.onclick=()=>activate(item);remove.onclick=()=>close(item);
    tab.onkeydown=event=>{if(['ArrowLeft','ArrowRight','Home','End','Delete'].includes(event.key)){event.preventDefault();if(event.key==='Delete'){close(item);return;}const all=[...sessions.values()],index=all.indexOf(item);const next=event.key==='Home'?0:event.key==='End'?all.length-1:(index+(event.key==='ArrowRight'?1:-1)+all.length)%all.length;activate(all[next],false);all[next].tab.focus();}};
    const socket=new WebSocket((location.protocol==='https:'?'wss:':'ws:')+'//'+location.host+'/api/terminal'+(mode==='model'?'?mode=model':''));item.socket=socket;
    term.onData(data=>{if(socket.readyState===1)socket.send(JSON.stringify({type:'input',data}));});
    socket.onopen=()=>resize(item);socket.onmessage=event=>{if(sessions.has(id))term.write(event.data);};
    socket.onclose=()=>{if(sessions.has(id)){tab.textContent+=(mode==='model'?' · finished':' · closed');term.write('\r\n\x1b[90mTerminal session ended.\x1b[0m\r\n');}};
    socket.onerror=()=>error(Error('Could not connect this terminal. Create a new terminal to try again.'));
    activate(item);
  }
  create.onclick=()=>open();new ResizeObserver(()=>resize(active)).observe(host);
  window.addEventListener('beforeunload',()=>{for(const item of sessions.values())item.socket?.close();});
  window.VisionTerminals={open,onError:handler=>{error=handler;}};
})();
