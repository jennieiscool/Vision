const {contextBridge,ipcRenderer,webUtils}=require('electron');
contextBridge.exposeInMainWorld('VisionDesktop',Object.freeze({
  window:action=>ipcRenderer.invoke('vision:window',action),
  hello:action=>ipcRenderer.invoke('vision:hello',action),
  pickFiles:()=>ipcRenderer.invoke('vision:open-files'),
  pickFolder:()=>ipcRenderer.invoke('vision:open-folder'),
  launchApp:id=>ipcRenderer.invoke('vision:launch-app',id),
  openEditor:id=>ipcRenderer.invoke('vision:open-editor',id),
  appViewport:(id,geometry)=>ipcRenderer.invoke('vision:app-viewport',id,geometry),
  appCapture:id=>ipcRenderer.invoke('vision:app-capture',id),
  filePath:file=>webUtils.getPathForFile(file),
  pasteImage:()=>ipcRenderer.invoke('vision:clipboard-image')
}));
