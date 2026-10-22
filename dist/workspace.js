const landing=document.querySelector('main');
const workspace=document.getElementById('workspace');
const transitionCanvas=document.getElementById('transition');
const transitionContext=transitionCanvas.getContext('2d');
let changingScreen=false, resumeAnimation=false;
// Mask the actual landing controls into particles, rather than popping them on at the end.
function landingFormation(assembling){
  const elements=[...landing.querySelectorAll('.controls button,.chat-launch,.voice-feedback,#ring-caption,#reply-caption')].filter(element=>!element.hidden&&element.getBoundingClientRect().width>0);
  const cx=offsetX+800*scale,cy=offsetY+410*scale;
  const pieces=elements.map((element,index)=>{
    const rect=element.getBoundingClientRect(),mask=document.createElement('canvas');mask.width=Math.max(1,Math.ceil(rect.width/5));mask.height=Math.max(1,Math.ceil(rect.height/5));
    return {element,rect,mask,context:mask.getContext('2d'),seed:index*19};
  });
  landing.classList.add('landing-forming');
  const update=(p,paint=true)=>{
    for(const piece of pieces){
      const {element,rect,mask,context,seed}=piece;context.clearRect(0,0,mask.width,mask.height);
      for(let y=0;y<mask.height;y++)for(let x=0;x<mask.width;x++){
        const noise=Math.abs(Math.sin(x*27.1+y*61.3+seed)*43758.54)%1;
        const amount=Math.max(0,Math.min(1,(p-noise*.24)/.65));const alpha=assembling?amount:1-amount;
        context.fillStyle=`rgba(255,255,255,${alpha})`;context.fillRect(x,y,1,1);
        if(!paint||x%2||y%2||amount<=0||amount>=1)continue;
        const targetX=rect.left+(x+.5)*5,targetY=rect.top+(y+.5)*5;
        const startX=cx+(targetX-cx)*.65,startY=cy+(targetY-cy)*.65;
        const travel=assembling?amount:1-amount;
        transitionContext.globalAlpha=Math.sin(amount*Math.PI)*.75;
        transitionContext.fillStyle='#f8d785';transitionContext.fillRect(startX+(targetX-startX)*travel,startY+(targetY-startY)*travel,1.5,1.5);
      }
      element.style.maskImage=`url(${mask.toDataURL()})`;element.style.maskSize='100% 100%';
    }
    transitionContext.globalAlpha=1;
  };
  update(0,false);
  return {update,finish(){for(const {element} of pieces){element.style.maskImage='';element.style.maskSize='';}landing.classList.remove('landing-forming');}};
}
function revealWorkspace(){
  landing.hidden=true;workspace.hidden=false;
  landing.classList.remove('transitioning');
  if(reducedMotion.matches){finishFormation();return;}
  formWorkspace();
}
function finishFormation(){
  workspace.classList.remove('forming');workspace.style.maskImage='';
  transitionCanvas.hidden=true;changingScreen=false;
  document.getElementById('back').focus();
}
function formWorkspace(){
  const w=innerWidth,h=innerHeight,dpr=Math.min(devicePixelRatio||1,2);
  transitionCanvas.width=Math.round(w*dpr);transitionCanvas.height=Math.round(h*dpr);
  transitionContext.setTransform(dpr,0,0,dpr,0,0);transitionCanvas.hidden=false;
  const mask=document.createElement('canvas');mask.width=Math.ceil(w/18);mask.height=Math.ceil(h/18);
  const maskContext=mask.getContext('2d'),cells=[],particles=[];
  for(let y=0;y<mask.height;y++)for(let x=0;x<mask.width;x++){
    const noise=Math.abs(Math.sin(x*18.31+y*73.17)*43758.54)%1;
    cells.push({x,y,delay:(x/mask.width)*.3+noise*.33});
  }
  const addParticle=(x,y,index)=>{
    const noise=Math.abs(Math.sin(index*37.17)*18367.31)%1;
    particles.push({x,y,dx:(noise-.5)*160,dy:-30-noise*90,delay:x/w*.3+noise*.25});
  };
  const grid=document.querySelector('.central-grid').getBoundingClientRect();
  let index=0;
  for(let x=grid.left;x<grid.right;x+=40)for(let y=grid.top;y<grid.bottom;y+=40)addParticle(x,y,index++);
  document.querySelectorAll('.panel,.workspace-header,.workspace-header button,.workspace-header .vision-picker,#preview-toolbar button,#preview-toolbar .vision-picker').forEach(panel=>{
    const rect=panel.getBoundingClientRect();
    for(let x=rect.left;x<rect.right;x+=13){addParticle(x,rect.top,index++);addParticle(x,rect.bottom,index++);}
    for(let y=rect.top;y<rect.bottom;y+=17){addParticle(rect.left,y,index++);addParticle(rect.right,y,index++);}
  });
  workspace.classList.add('forming');
  const updateMask=p=>{
    maskContext.clearRect(0,0,mask.width,mask.height);
    for(const cell of cells){
      const alpha=Math.max(0,Math.min(1,(p-cell.delay)/.28));
      if(!alpha)continue;
      maskContext.fillStyle=`rgba(255,255,255,${alpha})`;maskContext.fillRect(cell.x,cell.y,1,1);
    }
    workspace.style.maskImage=`url(${mask.toDataURL()})`;
  };
  updateMask(0);
  const start=performance.now();
  function assemble(now){
    const p=Math.min(1,(now-start)/1250);updateMask(p);
    transitionContext.clearRect(0,0,w,h);
    for(const particle of particles){
      const age=(p-particle.delay)/.4;
      if(age<0||age>1)continue;
      const remaining=1-age;
      transitionContext.globalAlpha=Math.sin(age*Math.PI)*.8;
      transitionContext.fillStyle='#f3d37b';
      transitionContext.fillRect(particle.x+particle.dx*remaining*remaining,particle.y+particle.dy*remaining*remaining,1.7,1.7);
    }
    transitionContext.globalAlpha=1;
    if(p<1)requestAnimationFrame(assemble);else finishFormation();
  }
  requestAnimationFrame(assemble);
}
document.getElementById('open-chat').addEventListener('click',()=>{
  if(changingScreen)return;
  changingScreen=true;resumeAnimation=playing;setPlaying(false);
  if(reducedMotion.matches){revealWorkspace();return;}
  const controlsFormation=landingFormation(false);
  landing.classList.add('transitioning');
  const w=innerWidth,h=innerHeight,dpr=canvas.width/w;
  const snapshot=document.createElement('canvas');snapshot.width=canvas.width;snapshot.height=canvas.height;
  snapshot.getContext('2d').drawImage(canvas,0,0);
  const pixels=snapshot.getContext('2d').getImageData(0,0,snapshot.width,snapshot.height).data;
  transitionCanvas.width=canvas.width;transitionCanvas.height=canvas.height;
  transitionContext.setTransform(dpr,0,0,dpr,0,0);
  const tiles=[],size=9;
  for(let y=0;y<h;y+=size)for(let x=0;x<w;x+=size){
    const pixel=(Math.min(snapshot.height-1,Math.floor((y+size/2)*dpr))*snapshot.width+Math.min(snapshot.width-1,Math.floor((x+size/2)*dpr)))*4;
    const hash=(Math.sin(x*12.9898+y*78.233)*43758.5453)%1;
    const noise=Math.abs(hash);
    tiles.push({x,y,delay:Math.min(.56,(1-x/w)*.3+noise*.26),vx:(noise-.3)*130,vy:-35-noise*95,color:`rgb(${pixels[pixel]},${pixels[pixel+1]},${pixels[pixel+2]})`,bright:pixels[pixel]>24});
  }
  canvas.style.visibility='hidden';transitionCanvas.hidden=false;
  const start=performance.now();
  function dissolve(now){
    const p=Math.min(1,(now-start)/1350);
    transitionContext.clearRect(0,0,w,h);
    transitionContext.globalAlpha=1;
    transitionContext.drawImage(snapshot,0,0,w,h);
    for(const tile of tiles){
      const age=(p-tile.delay)/.44;
      if(age<=0)continue;
      transitionContext.clearRect(tile.x,tile.y,size+1,size+1);
    }
    for(const tile of tiles){
      const age=(p-tile.delay)/.44;
      if(age<=0||age>=1||!tile.bright)continue;
      transitionContext.globalAlpha=(1-age)*(1-age);
      transitionContext.fillStyle=tile.color;
      const s=Math.max(.5,size*(1-age)*.65);
      transitionContext.fillRect(tile.x+tile.vx*age,tile.y+tile.vy*age,s,s);
    }
    transitionContext.globalAlpha=1;
    controlsFormation.update(p);
    if(p<1)requestAnimationFrame(dissolve);else {controlsFormation.finish();revealWorkspace();}
  }
  requestAnimationFrame(dissolve);
});
document.getElementById('back').addEventListener('click',()=>{
  if(changingScreen)return;
  changingScreen=true;
  let controlsFormation;
  const finishReturn=()=>{
    workspace.hidden=true;workspace.classList.remove('forming');workspace.style.maskImage='';
    landing.classList.remove('transitioning');canvas.style.opacity='';
    controlsFormation?.finish();
    transitionCanvas.hidden=true;changingScreen=false;setPlaying(resumeAnimation);
    document.getElementById('open-chat').focus();
  };
  landing.hidden=false;canvas.style.visibility='';resize();
  if(reducedMotion.matches){finishReturn();return;}
  landing.classList.add('transitioning');canvas.style.opacity='0';workspace.classList.add('forming');
  controlsFormation=landingFormation(true);
  const w=innerWidth,h=innerHeight,dpr=Math.min(devicePixelRatio||1,2);
  transitionCanvas.width=Math.round(w*dpr);transitionCanvas.height=Math.round(h*dpr);
  transitionContext.setTransform(dpr,0,0,dpr,0,0);transitionCanvas.hidden=false;
  const cx=offsetX+800*scale,cy=offsetY+410*scale;
  const mask=document.createElement('canvas');mask.width=Math.ceil(w/16);mask.height=Math.ceil(h/16);
  const maskContext=mask.getContext('2d'),cells=[],particles=[];
  for(let y=0;y<mask.height;y++)for(let x=0;x<mask.width;x++){
    const noise=Math.abs(Math.sin(x*17.31+y*61.17)*43758.54)%1;
    cells.push({x,y,delay:noise*.25});
  }
  function add(x,y,index){
    const noise=Math.abs(Math.sin(index*31.71)*43758.54)%1;
    const angle=Math.atan2(y-cy,x-cx);
    particles.push({x,y,tx:cx+Math.cos(angle)*100*scale,ty:cy+Math.sin(angle)*100*scale,delay:noise*.24,size:1.1+noise*1.6});
  }
  let index=0;
  const grid=document.querySelector('.central-grid').getBoundingClientRect();
  for(let x=grid.left;x<grid.right;x+=25)for(let y=grid.top;y<grid.bottom;y+=25)add(x,y,index++);
  document.querySelectorAll('.panel,.workspace-header,.workspace-header button,.workspace-header .vision-picker,#preview-toolbar button,#preview-toolbar .vision-picker').forEach(panel=>{
    const r=panel.getBoundingClientRect();
    for(let x=r.left;x<r.right;x+=10){add(x,r.top,index++);add(x,r.bottom,index++);}
    for(let y=r.top;y<r.bottom;y+=12){add(r.left,y,index++);add(r.right,y,index++);}
  });
  const start=performance.now();
  function converge(now){
    const p=Math.min(1,(now-start)/1650);
    maskContext.clearRect(0,0,mask.width,mask.height);
    for(const cell of cells){
      const alpha=1-Math.max(0,Math.min(1,(p-cell.delay)/.3));
      if(alpha<=0)continue;
      maskContext.fillStyle=`rgba(255,255,255,${alpha})`;maskContext.fillRect(cell.x,cell.y,1,1);
    }
    workspace.style.maskImage=`url(${mask.toDataURL()})`;
    canvas.style.opacity=String(Math.max(0,Math.min(1,(p-.18)/.66)));
    transitionContext.clearRect(0,0,w,h);
    transitionContext.fillStyle='#f6d575';
    for(const particle of particles){
      const age=Math.max(0,Math.min(1,(p-particle.delay)/.72));
      if(age<=0||age>=1)continue;
      const ease=age*age*(3-2*age);
      const x=particle.x+(particle.tx-particle.x)*ease,y=particle.y+(particle.ty-particle.y)*ease;
      const distance=Math.hypot(x-cx,y-cy)/scale;
      const absorption=Math.max(0,Math.min(1,(distance-101)/39));
      transitionContext.globalAlpha=Math.min(1,age*8)*absorption*.85;
      const size=particle.size*(1-age*.65);
      transitionContext.fillRect(x,y,size,size);
    }
    transitionContext.globalAlpha=1;
    controlsFormation.update(Math.max(0,(p-.25)/.75));
    if(p<1)requestAnimationFrame(converge);else finishReturn();
  }
  requestAnimationFrame(converge);
});
document.querySelector('.composer').addEventListener('submit',event=>event.preventDefault());
