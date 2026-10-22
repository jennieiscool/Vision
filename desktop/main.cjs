const {app,BrowserWindow,session,dialog,Menu,ipcMain,clipboard,shell,desktopCapturer,screen}=require('electron');
const {spawn}=require('node:child_process');
const path=require('node:path');
const fs=require('node:fs');
const http=require('node:http');
const desktopSecret=require('node:crypto').randomBytes(32).toString('hex');
const rootFile=path.join(__dirname,'vision-root.json');
const root=fs.existsSync(rootFile)?JSON.parse(fs.readFileSync(rootFile,'utf8')).root:path.resolve(__dirname,'..');
app.setPath('userData',path.join(root,'runtime/desktop-profile'));
app.setAppUserModelId('Vision.Desktop');
let backend,window,closing=false;
let windowsDetached=false;
const origin='http://127.0.0.1:8787';
if(!app.requestSingleInstanceLock()){app.exit(0);}
app.on('second-instance',()=>{if(window&&!window.isDestroyed()){if(window.isMinimized())window.restore();window.show();window.focus();}});
function reachable(){return new Promise(resolve=>{const request=http.get(origin+'/',response=>{response.resume();resolve(response.statusCode===200);});request.on('error',()=>resolve(false));request.setTimeout(800,()=>{request.destroy();resolve(false);});});}
async function startBackend(){
  if(await reachable())return;
  const runtime=path.join(root,'runtime');fs.mkdirSync(runtime,{recursive:true});
  const output=fs.openSync(path.join(runtime,'desktop-backend.log'),'a');
  const python=process.platform==='win32'?path.join(root,'.venv','Scripts','python.exe'):path.join(root,'.venv','bin','python');
  backend=spawn(python,['-m','uvicorn','backend.server:app','--host','127.0.0.1','--port','8787'],{cwd:root,windowsHide:true,stdio:['ignore',output,output],env:{...process.env,PYTHONIOENCODING:'utf-8',VISION_DESKTOP_SECRET:desktopSecret,VISION_DESKTOP_PID:String(process.pid)}});
  backend.on('error',error=>dialog.showErrorBox('Vision backend',error.message));
  for(let i=0;i<100;i++){if(await reachable())return;await new Promise(resolve=>setTimeout(resolve,200));}
  throw Error('The local Vision bridge did not start. See runtime/desktop-backend.log.');
}
function trusted(event){if(!event.senderFrame?.url.startsWith(origin+'/'))throw Error('Desktop access denied');}
ipcMain.handle('vision:window',(event,action)=>{trusted(event);if(action==='minimize')window.minimize();else if(action==='maximize'){if(window.isMaximized())window.unmaximize();else window.maximize();}else if(action==='close')window.close();else if(action==='signin-settings'&&process.platform==='win32')shell.openExternal('ms-settings:signinoptions');});
ipcMain.handle('vision:open-files',async event=>{trusted(event);const result=await dialog.showOpenDialog(window,{title:'Open files in Vision',properties:['openFile','multiSelections']});return result.canceled?[]:result.filePaths;});
ipcMain.handle('vision:open-folder',async event=>{trusted(event);const result=await dialog.showOpenDialog(window,{title:'Open a Vision workspace',properties:['openDirectory','createDirectory']});return result.canceled?'':result.filePaths[0];});
ipcMain.handle('vision:launch-app',async(event,id)=>{
  trusted(event);if(typeof id!=='string'||!/^[a-f0-9]{24}$/.test(id))throw Error('Invalid application');
  return launchManaged(await bridge('/api/app-library/'+id+'/launch',{}));
});
async function bridge(route,data){
  const cookies=await session.defaultSession.cookies.get({url:origin});
  const response=await fetch(origin+route,{method:data===undefined?'GET':'POST',headers:{'Content-Type':'application/json',Origin:origin,Cookie:cookies.map(c=>c.name+'='+c.value).join('; '),'x-vision-desktop':desktopSecret},body:data===undefined?undefined:JSON.stringify(data)});
  const result=await response.json();if(!response.ok)throw Error(result.detail||'Application access failed.');return result;
}
async function launchManaged(spec){
  windowsDetached=false;
  // Start outside the bridge process tree: closing Vision detaches the window
  // without terminating unsaved work in the user's application.
  const child=spawn(spec.executable,spec.args||[],{cwd:spec.directory,detached:true,stdio:'ignore',windowsHide:false});
  await new Promise((resolve,reject)=>{child.once('spawn',resolve);child.once('error',reject);});child.unref();
  return bridge('/api/app-control/desktop-register',{...spec,pid:child.pid});
}
ipcMain.handle('vision:open-editor',async(event,id)=>{trusted(event);if(typeof id!=='string'||!/^[a-f0-9]{24}$/.test(id))throw Error('Invalid workspace');return launchManaged(await bridge('/api/app-control/editor/'+id,{}));});
ipcMain.handle('vision:app-viewport',async(event,id,geometry)=>{
  trusted(event);if(typeof id!=='string'||!/^[a-f0-9]{24}$/.test(id))throw Error('Invalid application session');
  const handle=window.getNativeWindowHandle(),owner=(handle.length>=8?handle.readBigUInt64LE():BigInt(handle.readUInt32LE())).toString();
  const scale=screen.getDisplayMatching(window.getBounds()).scaleFactor*window.webContents.getZoomFactor();
  const rect=(geometry?.rect||[]).map(value=>Math.round(Number(value)*scale));
  return bridge('/api/app-control/desktop/'+id,{owner,rect,visible:!!geometry?.visible&&!window.isMinimized()&&window.isVisible()});
});
ipcMain.handle('vision:app-capture',async(event,id)=>{
  trusted(event);if(typeof id!=='string'||!/^[a-f0-9]{24}$/.test(id))throw Error('Invalid application session');
  const target=await bridge('/api/app-control/sessions/'+id);if(!target.hwnd)throw Error('Choose an application window first.');
  const sources=await desktopCapturer.getSources({types:['window'],thumbnailSize:{width:0,height:0},fetchWindowIcons:false});
  const source=sources.find(item=>{try{return BigInt(item.id.split(':')[1])===BigInt(target.hwnd);}catch{return false;}});
  if(!source)throw Error('The desktop did not expose this application as a live capture source. Keep its window open and visible, then try again.');return source.id;
});
ipcMain.handle('vision:clipboard-image',event=>{trusted(event);const image=clipboard.readImage();return image.isEmpty()?null:image.toDataURL();});
ipcMain.handle('vision:hello',async(event,action)=>{
  trusted(event);if(!['availability','verify'].includes(action))throw Error('Invalid authentication action');
  if(process.platform!=='win32')return {result:'Unavailable',message:'Windows Hello is only available on Windows.'};
  const result=await new Promise((resolve,reject)=>{const child=spawn('powershell.exe',['-NoProfile','-NonInteractive','-File',path.join(root,'desktop/windows-hello.ps1'),'-Action',action],{windowsHide:true});let output='';child.stdout.on('data',chunk=>output+=chunk);child.on('error',reject);child.on('close',()=>{try{resolve(JSON.parse(output));}catch{resolve({result:'Unavailable'});}});});
  if(action==='verify'&&result.result==='Verified'){
    const cookies=await session.defaultSession.cookies.get({url:origin});
    const response=await fetch(origin+'/api/desktop/security',{method:'POST',headers:{'Content-Type':'application/json',Origin:origin,Cookie:cookies.map(c=>c.name+'='+c.value).join('; '),'x-vision-desktop':desktopSecret},body:JSON.stringify({action:'unlock',hello:true})});
    if(!response.ok)throw Error('Vision could not unlock. Try your app password.');
  }
  return result;
});
app.whenReady().then(async()=>{
  session.defaultSession.setPermissionRequestHandler((contents,permission,callback)=>{
    const trusted=contents.getURL().startsWith(origin+'/');
    callback(trusted&&['media','display-capture','fullscreen','clipboard-sanitized-write','clipboard-read'].includes(permission));
  });
  session.defaultSession.setPermissionCheckHandler((contents,permission,requestingOrigin)=>requestingOrigin===origin&&['media','display-capture','fullscreen','clipboard-sanitized-write','clipboard-read'].includes(permission));
  await startBackend();
  window=new BrowserWindow({width:1536,height:960,minWidth:820,minHeight:620,title:'Vision',backgroundColor:'#030201',autoHideMenuBar:true,frame:false,icon:path.join(root,'desktop/assets',process.platform==='win32'?'vision.ico':'vision.png'),webPreferences:{preload:path.join(__dirname,'preload.cjs'),nodeIntegration:false,contextIsolation:true,sandbox:true,webSecurity:true}});
  window.on('close',event=>{if(windowsDetached)return;event.preventDefault();bridge('/api/app-control/desktop-detach-all',{}).then(()=>{windowsDetached=true;window.close();}).catch(error=>dialog.showErrorBox('Close applications first','Vision could not detach an application window: '+error.message));});
  window.webContents.setWindowOpenHandler(()=>({action:'deny'}));
  window.webContents.on('will-navigate',(event,url)=>{if(!url.startsWith(origin+'/'))event.preventDefault();});
  window.webContents.on('did-finish-load',()=>window.setTitle('Vision'));
  window.webContents.on('context-menu',(_event,params)=>{
    const items=[];
    if(params.isEditable)items.push({role:'cut',enabled:params.editFlags.canCut},{role:'copy',enabled:params.editFlags.canCopy},{role:'paste',enabled:params.editFlags.canPaste},{role:'selectAll'});
    else if(params.selectionText)items.push({role:'copy'},{role:'selectAll'});
    if(params.mediaType==='image')items.push({label:'Copy image',click:()=>window.webContents.copyImageAt(params.x,params.y)},{label:'Save image…',click:()=>window.webContents.downloadURL(params.srcURL)});
    if(items.length)Menu.buildFromTemplate(items).popup({window});
  });
  await window.loadURL(origin);
  window.show();
  window.focus();
}).catch(error=>{dialog.showErrorBox('Vision could not start',error.message);app.quit();});
app.on('window-all-closed',()=>app.quit());
app.on('before-quit',event=>{
  if(!backend||closing)return;
  closing=true;event.preventDefault();
  (async()=>{
    if(!windowsDetached){await bridge('/api/app-control/desktop-detach-all',{});windowsDetached=true;}
    // Managed applications were launched by Electron and detached above. Only
    // the bridge-owned gateway, browser and terminals belong to this tree.
    if(process.platform==='win32'){
      const killer=spawn('taskkill',['/PID',String(backend.pid),'/T','/F'],{windowsHide:true,stdio:'ignore'});
      killer.on('exit',()=>app.quit());killer.on('error',()=>app.quit());
    }else{backend.once('exit',()=>app.quit());backend.kill('SIGTERM');setTimeout(()=>app.quit(),2500).unref();}
  })().catch(error=>{closing=false;dialog.showErrorBox('Vision could not close',error.message);});
});
