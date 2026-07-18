const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('fgbStudio', {
  selectVideo: () => ipcRenderer.invoke('shorts:select-video'),
  selectTranscript: () => ipcRenderer.invoke('shorts:select-transcript'),
  selectOutput: () => ipcRenderer.invoke('shorts:select-output'),
  generateShorts: (input) => ipcRenderer.invoke('shorts:generate', input),
  selectAudio: () => ipcRenderer.invoke('audio-shorts:select-audio'),
  selectAudioTranscript: () => ipcRenderer.invoke('audio-shorts:select-transcript'),
  selectVisualAssets: () => ipcRenderer.invoke('audio-shorts:select-visuals'),
  selectAudioOutput: () => ipcRenderer.invoke('audio-shorts:select-output'),
  getAudioShortsSettings: () => ipcRenderer.invoke('audio-shorts:get-settings'),
  saveOpenAIKey: (apiKey) => ipcRenderer.invoke('audio-shorts:save-api-key', apiKey),
  clearOpenAIKey: () => ipcRenderer.invoke('audio-shorts:clear-api-key'),
  generateAudioShorts: (input) => ipcRenderer.invoke('audio-shorts:generate', input),
  openPath: (targetPath) => ipcRenderer.invoke('shorts:open-path', targetPath),
  onShortsProgress: (listener) => {
    const handler = (_event, payload) => listener(payload);
    ipcRenderer.on('shorts:progress', handler);
    return () => ipcRenderer.removeListener('shorts:progress', handler);
  },
  onAudioShortsProgress: (listener) => {
    const handler = (_event, payload) => listener(payload);
    ipcRenderer.on('audio-shorts:progress', handler);
    return () => ipcRenderer.removeListener('audio-shorts:progress', handler);
  },
});
