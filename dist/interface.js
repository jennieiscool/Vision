const canvas = document.getElementById('interface');
const ctx = canvas.getContext('2d');
const TAU = Math.PI * 2;
const reducedMotion = matchMedia('(prefers-reduced-motion: reduce)');
let playing = !reducedMotion.matches, elapsed = 0, last = 0, frame;
let width, height, scale, offsetX, offsetY;
let seed = 92;
function random(){seed=(seed*1664525+1013904223)>>>0;return seed/4294967296}
const digits = Array.from({length:16},()=>Array.from({length:95},()=>random()>.5?'1':'0').join(' '));
const traces = Array.from({length:24},(_,i)=>({left:i<14,y:i<14?30+i*23:420+(i-14)*20,x:290+random()*75,end:470+random()*140}));

function resize(){
  width=innerWidth;height=innerHeight;
  const dpr=Math.min(devicePixelRatio||1,2);
  canvas.width=Math.round(width*dpr);canvas.height=Math.round(height*dpr);
  // Preserve the reference composition on wide screens and its central rings on portrait screens.
  scale=Math.min(width/1600,height/800);
  if(width/height<1.25)scale=Math.min(width/760,height/800);
  offsetX=(width-1600*scale)/2;offsetY=(height-800*scale)/2;
  ctx.setTransform(dpr,0,0,dpr,0,0);draw();
}
function arc(r,a,b,line,color,glow=0){
  ctx.beginPath();ctx.arc(800,410,r,a,b);ctx.lineWidth=line;ctx.strokeStyle=color;
  ctx.shadowColor=color;ctx.shadowBlur=glow;ctx.stroke();ctx.shadowBlur=0;
}
function glow(x,y,r,color){const g=ctx.createRadialGradient(x,y,0,x,y,r);g.addColorStop(0,color);g.addColorStop(1,'transparent');ctx.fillStyle=g;ctx.fillRect(x-r,y-r,r*2,r*2)}
function circuit(points,alpha){
  ctx.beginPath();points.forEach(([x,y],i)=>i?ctx.lineTo(x,y):ctx.moveTo(x,y));
  ctx.lineWidth=1.5;ctx.strokeStyle=`rgba(224,155,27,${alpha*1.65})`;ctx.shadowColor='#efb927';ctx.shadowBlur=7;ctx.stroke();ctx.shadowBlur=0;
  const [x,y]=points[points.length-1];ctx.beginPath();ctx.arc(x,y,5,0,TAU);ctx.fillStyle=`rgba(222,139,15,${alpha*1.3})`;ctx.fill();
}
// A steady, straight inward pull toward the inner rim.
// Light is absorbed just inside the innermost outline, powering the rim.
function infallPoint(x,y,progress){
  const dx=x-800,dy=y-410;
  const radius=132+(Math.hypot(dx,dy)-132)*(1-progress);
  const angle=Math.atan2(dy,dx);
  return {x:800+Math.cos(angle)*radius,y:410+Math.sin(angle)*radius,radius};
}
function drawInfall(t){
  ctx.save();ctx.textAlign='center';ctx.textBaseline='middle';
  ctx.shadowColor='#eebb32';ctx.shadowBlur=3;
  digits.forEach((line,i)=>{
    if(i%2) return;
    for(let j=(i%4)*2;j<line.length;j+=12){
      const x=65+j*8,y=294+i*15.7;
      if(Math.hypot(x-800,y-410)<154)continue;
      const p=(t/18+i*.061+j*.013)%1;
      const point=infallPoint(x,y,p);
      const opacity=Math.min(1,p*9)*Math.min(1,(point.radius-132)/28);
      if(opacity<=0)continue;
      ctx.font=`${Math.max(5,15*(1-p*.65))}px monospace`;
      ctx.fillStyle=`rgba(255,215,79,${opacity*.32})`;
      ctx.fillText(line[j],point.x,point.y);
    }
  });
  ctx.restore();
}
function draw(){
  ctx.clearRect(0,0,width,height);ctx.fillStyle='#030201';ctx.fillRect(0,0,width,height);
  ctx.save();ctx.translate(offsetX,offsetY);ctx.scale(scale,scale);
  const t=elapsed*.001;
  glow(800,410,730,'#3b200a');glow(800,410,490,'#8060008c');
  traces.forEach((p,i)=>{
    if(p.left)circuit([[40,p.y],[p.x-50,p.y],[p.x+40,p.y+90],[p.end-40,p.y+90],[p.end,p.y+130]],.07+(i%5)*.028);
    else circuit([[1030,p.y],[1170,p.y],[1270,p.y+100],[1540,p.y+100]],.11+(i%3)*.025);
  });
  for(let i=0;i<9;i++){
    circuit([[40,285+i*20],[325+i*4,285+i*20],[390+i*4,350+i*20],[575,350+i*20]],.11);
    circuit([[1025,440+i*19],[1200,440+i*19],[1270,510+i*19],[1555,510+i*19]],.13);
  }
  ctx.font='16px monospace';ctx.textAlign='left';
  ctx.shadowColor='#eabd34';ctx.shadowBlur=5;
  digits.forEach((line,i)=>{
    for(let j=0;j<line.length;j+=2){
      const x=65+j*8,y=294+i*15.7;
      const near=Math.max(0,1-Math.abs(x-800)/500);
      ctx.fillStyle=`rgba(241,193,38,${.07+near*.19+(Math.sin(j*.7+i+t*.5)>.94?.19:0)})`;
      ctx.fillText(line[j],x,y);
    }
  });
  ctx.shadowBlur=0;
  drawInfall(t);
  // Soft bloom sits behind precise machined rings, leaving the core empty.
  arc(228,0,TAU,100,'#bfa70b22',65);
  arc(246,0,TAU,54,'#e4bd1614',90);
  arc(291,0,TAU,7,'#e9de7060',14);
  arc(297,0,TAU,1.4,'#eedb70a0',5);
  arc(262,0,TAU,1.2,'#cba41b9c');
  arc(242,0,TAU,3,'#fff17c9c',9);
  arc(232,0,TAU,1.5,'#fff3a6a8',5);
  arc(213,0,TAU,19,'#b08a0740',15);
  const turn=t*.0175;
  [[-1.17,.38],[.12,.32],[1.23,.32],[2.09,.34],[2.75,.65],[3.73,.61]].forEach(([a,n],i)=>arc(297,a+turn,a+n+turn,17,i%2?'#ffcd208c':'#e8b519a8',12));
  [[-1.51,.45],[-.91,.35],[-.39,.58],[.43,.39],[.89,.93],[2.1,.44],[2.56,.41],[3.3,.44],[4.03,.28]].forEach(([a,n],i)=>arc(260,a-turn*.7,a+n-turn*.7,24,i%3?'#f5c82dc9':'#db9d0dc9',10));
  [[-.94,.72],[.05,.72],[1.23,.6],[2.12,.49],[2.92,.48],[3.8,.69],[4.7,.18]].forEach(([a,n],i)=>arc(240,a+turn*.65,a+n+turn*.65,11,i%2?'#fff646cb':'#e9d32bc7',9));
  arc(219,-3.05+turn, -1.55+turn,15,'#d89d06bb',12);
  arc(219,-1.58+turn,-.84+turn,15,'#ffbf00bd',9);
  arc(217,.51+turn,2.03+turn,19,'#b9780599',10);
  for(let i=0;i<152;i++){
    const a=i/152*TAU-turn*.6;
    if(i>14&&i<63)continue;
    arc(210,a,a+.024,13,i<86?'#e8be0ade':'#ffb70acf',5);
  }
  arc(195,0,TAU,2,'#efe35a92',7);
  arc(178,0,TAU,1.5,'#f7e456a1',6);
  for(let i=0;i<125;i++){
    const a=i/125*TAU+turn*.85;
    if(i>31&&i<64)continue;
    arc(167,a,a+.023,12,'#f7e331c9',7);
  }
  arc(151,0,TAU,3,'#f9e95c8c',14);
  arc(143,0,TAU,7,'#dac12451',20);
  // The black center and feathered edge reproduce the depth of the reference.
  const core=ctx.createRadialGradient(800,410,96,800,410,154);
  core.addColorStop(0,'#000');core.addColorStop(.63,'#000');core.addColorStop(.86,'#050300eb');core.addColorStop(1,'#1c140000');
  ctx.fillStyle=core;ctx.beginPath();ctx.arc(800,410,154,0,TAU);ctx.fill();
  // A narrow absorption band blends the incoming light into the last outline.
  // The interior stays empty while the rim softly brightens with arriving energy.
  ctx.save();ctx.beginPath();ctx.arc(800,410,144,0,TAU);ctx.clip();drawInfall(t);ctx.restore();
  const rimIntensity=.63+Math.sin(t*.9)*.055;
  arc(145,0,TAU,17,`rgba(242,183,24,${rimIntensity*.48})`,40);
  arc(143,0,TAU,8,`rgba(255,215,70,${rimIntensity})`,24);
  arc(142,0,TAU,2.8,'#fff0b6ed',12);
  for(let lane=0;lane<36;lane++){
    const side=lane%2?-1:1;
    const point=infallPoint(800+side*(570+(lane%4)*42),150+(lane*73)%520,(t/18+lane*.137)%1);
    const intensity=Math.exp(-Math.pow((point.radius-148)/38,2))*.9;
    if(intensity<.02)continue;
    const angle=Math.atan2(point.y-410,point.x-800);
    arc(143,angle-.18,angle+.18,7,`rgba(255,235,156,${intensity})`,27);
  }
  const vignette=ctx.createRadialGradient(800,400,260,800,400,850);
  vignette.addColorStop(0,'transparent');vignette.addColorStop(.65,'#00000042');vignette.addColorStop(1,'#000000ed');
  ctx.fillStyle=vignette;ctx.fillRect(0,0,1600,800);ctx.restore();
}
function loop(now){if(last)elapsed+=Math.min(now-last,60);last=now;draw();if(playing)frame=requestAnimationFrame(loop)}
function setPlaying(value){playing=value;cancelAnimationFrame(frame);last=0;if(playing)frame=requestAnimationFrame(loop)}
reducedMotion.addEventListener('change',e=>setPlaying(!e.matches));
const fullscreen=document.getElementById('fullscreen');
if(!document.documentElement.requestFullscreen)fullscreen.hidden=true;
fullscreen.addEventListener('click',async()=>{try{if(document.fullscreenElement)await document.exitFullscreen();else await document.documentElement.requestFullscreen()}catch{fullscreen.hidden=true}});
document.addEventListener('fullscreenchange',()=>{const label=document.fullscreenElement?'Exit fullscreen':'Enter fullscreen';fullscreen.setAttribute('aria-label',label);fullscreen.title=label});
window.addEventListener('resize',resize);resize();setPlaying(playing);
