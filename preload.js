const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('fgbStudio', {
  selectVideo: () => ipcRenderer.invoke('shorts:select-video'),
  selectTranscript: () => ipcRenderer.invoke('shorts:select-transcript'),
  selectOutput: () => ipcRenderer.invoke('shorts:select-output'),
  generateShorts: (input) => ipcRenderer.invoke('shorts:generate', input),
  openPath: (targetPath) => ipcRenderer.invoke('shorts:open-path', targetPath),
  onShortsProgress: (listener) => {
    const handler = (_event, payload) => listener(payload);
    ipcRenderer.on('shorts:progress', handler);
    return () => ipcRenderer.removeListener('shorts:progress', handler);
  },
});
