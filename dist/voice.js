/* Local PCM capture keeps pre-roll and uses the same unlocked audio context for replies. */
class VisionVoice {
  constructor(options){
    this.closed=false;this.options=options;this.enabled=false;this.epoch=0;this.context=null;
    this.speaking=false;this.transcribing=false;this.floor=.002;this.resetCapture();
    this.playbackBuffer=null;this.playbackOffset=0;this.paused=false;
    this.captionWords=[];this.captionFrame=0;
    this.speechRequest=0;
    this.outputEnabled=true;this.deviceId='';
  }
  resetCapture(){this.frames=[];this.preRoll=[];this.preSamples=0;this.samples=0;this.voiced=0;this.silence=0;}
  status(text){this.options.status(text,{mic:this.enabled,output:this.outputEnabled,speaking:this.speaking,paused:this.paused});}
  async unlockAudio(){if(!this.context||this.context.state==='closed')this.context=new AudioContext();await this.context.resume();}
  async unmute(deviceId){
    if(!this.options.connected()){this.options.error(Error('Connect Vision before enabling voice.'));return;}
    if(this.enabled)await this.mute();
    try{
      this.stream=await navigator.mediaDevices.getUserMedia({audio:{echoCancellation:true,noiseSuppression:true,autoGainControl:true,...(deviceId?{deviceId:{exact:deviceId}}:{})}});
      this.deviceId=deviceId||'';await this.unlockAudio();
      this.source=this.context.createMediaStreamSource(this.stream);
      this.processor=this.context.createScriptProcessor(2048,1,1);
      this.silentOutput=this.context.createGain();this.silentOutput.gain.value=0;
      this.source.connect(this.processor);this.processor.connect(this.silentOutput);this.silentOutput.connect(this.context.destination);
      this.enabled=true;this.epoch++;this.resetCapture();this.floor=.002;
      this.options.enabled(true);this.status('Listening — speak, then pause');
      this.processor.onaudioprocess=event=>this.capture(event.inputBuffer.getChannelData(0));
      await this.updateDevices();
      this.stream.getAudioTracks()[0].onended=()=>{if(this.enabled){this.mute();this.options.error(Error('The microphone disconnected. Select a microphone and unmute again.'));}};
    }catch(error){await this.mute();this.options.error(Error('Microphone unavailable: '+error.message));}
  }
  async updateDevices(){
    const select=document.getElementById('microphone-select');if(!select)return;
    const selected=this.stream?.getAudioTracks()[0]?.getSettings().deviceId||this.deviceId;
    const devices=(await navigator.mediaDevices.enumerateDevices()).filter(device=>device.kind==='audioinput');
    select.replaceChildren(new Option('System default microphone',''));
    for(const [index,device] of devices.entries()){const option=new Option(device.label||'Audio input '+(index+1),device.deviceId);option.selected=device.deviceId===selected;select.append(option);}
    select.disabled=false;this.options.devices?.(devices);window.dispatchEvent(new CustomEvent('vision:audio-devices',{detail:devices}));
  }
  async refreshDevices(){if(!this.enabled){const permission=await navigator.mediaDevices.getUserMedia({audio:true});permission.getTracks().forEach(track=>track.stop());}await this.updateDevices();}
  capture(input){
    if(!this.enabled||!this.context)return;
    const rate=this.context.sampleRate, duration=input.length/rate;
    let power=0;for(const sample of input)power+=sample*sample;
    const rms=Math.sqrt(power/input.length);this.options.level(Math.min(1,rms*12));
    if(this.transcribing||this.speaking||!this.options.canListen()){
      this.resetCapture();
      if(!this.transcribing&&!this.speaking)this.status('Vision is working…');
      return;
    }
    const threshold=Math.max(.004,Math.min(.025,this.floor*2.8));
    const speech=rms>threshold;
    if(!speech&&!this.frames.length)this.floor=this.floor*.97+rms*.03;
    const frame=new Float32Array(input);
    if(!this.frames.length){
      this.preRoll.push(frame);this.preSamples+=frame.length;
      while(this.preSamples>rate*.4&&this.preRoll.length>1)this.preSamples-=this.preRoll.shift().length;
      if(!speech)return;
      this.frames=this.preRoll;this.samples=this.preSamples;this.preRoll=[];this.preSamples=0;
      this.voiced=duration;this.silence=0;this.status('Hearing you…');return;
    }
    this.frames.push(frame);this.samples+=frame.length;
    if(speech){this.voiced+=duration;this.silence=0;}else this.silence+=duration;
    if(this.silence>=1.05||this.samples/rate>=20){
      if(this.voiced>=.08){const frames=this.frames;this.resetCapture();this.transcribe(frames,rate,this.epoch);}
      else {this.resetCapture();this.status('Listening — speak, then pause');}
    }
  }
  wav(frames,rate){
    const length=frames.reduce((count,frame)=>count+frame.length,0);
    let peak=0;for(const frame of frames)for(const value of frame)peak=Math.max(peak,Math.abs(value));
    const gain=peak>.001?Math.min(6,.85/peak):1;
    const buffer=new ArrayBuffer(44+length*2),view=new DataView(buffer);
    const str=(offset,text)=>{for(let i=0;i<text.length;i++)view.setUint8(offset+i,text.charCodeAt(i));};
    str(0,'RIFF');view.setUint32(4,36+length*2,true);str(8,'WAVE');str(12,'fmt ');
    view.setUint32(16,16,true);view.setUint16(20,1,true);view.setUint16(22,1,true);view.setUint32(24,rate,true);view.setUint32(28,rate*2,true);view.setUint16(32,2,true);view.setUint16(34,16,true);str(36,'data');view.setUint32(40,length*2,true);
    let offset=44;for(const frame of frames)for(const value of frame){const sample=Math.max(-1,Math.min(1,value*gain));view.setInt16(offset,sample<0?sample*32768:sample*32767,true);offset+=2;}
    return new Blob([buffer],{type:'audio/wav'});
  }
  async transcribe(frames,rate,epoch){
    const generation=this.inputGeneration||0;
    this.transcribing=true;this.status('Recognizing speech…');
    this.transcriptionAbort=new AbortController();
    try{
      const form=new FormData();form.append('audio',this.wav(frames,rate),'speech.wav');
      const response=await fetch('/api/voice/transcribe',{method:'POST',body:form,signal:this.transcriptionAbort.signal});
      const result=await response.json();
      if(!response.ok)throw Error(result.detail||'Speech recognition failed');
      if(this.closed||generation!==(this.inputGeneration||0))return;
      if(!result.text?.trim()){this.status('No speech recognized — check your microphone');return;}
      this.status('Vision is thinking…');await this.options.transcript(result.text.trim());
    }catch(error){if(error.name!=='AbortError'){this.status('Voice input failed');this.options.error(error);}}
    finally{this.transcribing=false;}
  }
  async speak(text){
    if(!this.outputEnabled)return;
    await this.unlockAudio();
    const request=++this.speechRequest;
    this.speechAbort?.abort();
    if(this.player){this.player.onended=null;this.player.stop();}
    if(this.playbackBuffer)this.finishPlayback();
    const epoch=this.epoch;this.speaking=true;this.resetCapture();this.status('Preparing Kokoro voice…');
    this.speechAbort=new AbortController();let failed=false;
    try{
      const response=await fetch('/api/voice/speak',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({text:text.slice(0,6000),timings:true}),signal:this.speechAbort.signal});
      if(!response.ok){const error=await response.json();throw Error(error.detail||'Kokoro voice generation failed');}
      const speech=await response.json();
      if(speech.silent)return;
      const bytes=Uint8Array.from(atob(speech.audio),character=>character.charCodeAt(0)).buffer;
      if(!this.outputEnabled||request!==this.speechRequest)return;
      await this.context.resume();const decoded=await this.context.decodeAudioData(bytes);
      if(!this.outputEnabled||request!==this.speechRequest)return;
      await new Promise(resolve=>{
        this.playbackDone=resolve;this.playbackBuffer=decoded;this.playbackOffset=0;this.paused=false;this.captionWords=speech.words||[];
        this.startPlayback();
      });
    }catch(error){if(error.name!=='AbortError'&&request===this.speechRequest){failed=true;this.status('Voice playback failed');this.options.error(error);}}
    finally{if(request===this.speechRequest){this.speaking=false;this.resetCapture();if(!failed)this.status(this.enabled?'Listening':'Microphone muted');}}
  }
  playbackChanged(){this.options.playback?.({active:!!this.playbackBuffer,paused:this.paused});}
  startPlayback(){
    if(!this.playbackBuffer||!this.context)return;
    const player=this.context.createBufferSource();player.buffer=this.playbackBuffer;player.connect(this.context.destination);
    this.player=player;this.playbackStarted=this.context.currentTime;this.paused=false;
    player.onended=()=>{if(this.player!==player)return;this.finishPlayback();};
    player.start(0,this.playbackOffset);this.status('Vision is speaking…');this.playbackChanged();
    this.trackCaptions();
  }
  trackCaptions(){
    cancelAnimationFrame(this.captionFrame);
    const tick=()=>{
      if(!this.playbackBuffer||this.paused||!this.context)return;
      // Use the audio device's playback clock, not a reading-speed timer.
      const stamp=this.context.getOutputTimestamp?.();
      const heardTime=stamp?.contextTime>0?stamp.contextTime+(performance.now()-stamp.performanceTime)/1000:this.context.currentTime-(this.context.outputLatency||0);
      const position=Math.max(0,this.playbackOffset+heardTime-this.playbackStarted);
      this.options.captions?.({words:this.captionWords,position,active:true});
      this.captionFrame=requestAnimationFrame(tick);
    };
    this.captionFrame=requestAnimationFrame(tick);
  }
  pausePlayback(){
    if(!this.player||this.paused||!this.playbackBuffer)return;
    this.playbackOffset=Math.min(this.playbackBuffer.duration,this.playbackOffset+this.context.currentTime-this.playbackStarted);
    const player=this.player;this.player=null;player.onended=null;player.stop();player.disconnect();
    this.paused=true;this.status('Speech paused');this.playbackChanged();
    cancelAnimationFrame(this.captionFrame);
  }
  async resumePlayback(){
    if(!this.paused||!this.playbackBuffer||!this.context)return;
    await this.context.resume();
    if(this.playbackOffset>=this.playbackBuffer.duration){this.finishPlayback();return;}
    this.startPlayback();
  }
  finishPlayback(){
    cancelAnimationFrame(this.captionFrame);this.captionWords=[];this.options.captions?.({words:[],position:0,active:false});
    this.player?.disconnect();this.player=null;this.playbackBuffer=null;this.playbackOffset=0;this.paused=false;
    this.playbackChanged();const done=this.playbackDone;this.playbackDone=null;done?.();
  }
  resetConversation(){
    this.inputGeneration=(this.inputGeneration||0)+1;this.transcriptionAbort?.abort();
    this.speechRequest++;this.speechAbort?.abort();
    if(this.player){this.player.onended=null;this.player.stop();}
    this.finishPlayback();this.speaking=false;this.resetCapture();
  }
  async mute(){
    this.enabled=false;this.epoch++;
    if(this.processor){this.processor.onaudioprocess=null;this.processor.disconnect();}
    this.source?.disconnect();this.silentOutput?.disconnect();
    this.stream?.getTracks().forEach(track=>{track.onended=null;track.stop();});
    this.stream=null;this.source=null;this.processor=null;this.silentOutput=null;
    this.resetCapture();this.options.level(0);this.options.enabled(false);this.status('Microphone muted');
  }
  async setOutputEnabled(value){
    this.outputEnabled=value;this.options.outputEnabled?.(value);
    if(value)await this.unlockAudio();
    else{this.speechRequest++;this.speechAbort?.abort();if(this.player){this.player.onended=null;this.player.stop();}this.finishPlayback();this.speaking=false;}
    this.status(value?'Speech enabled':'Speech muted');
  }
  async close(){this.closed=true;this.transcriptionAbort?.abort();await this.mute();await this.setOutputEnabled(false);if(this.context&&this.context.state!=='closed')await this.context.close();}
}
