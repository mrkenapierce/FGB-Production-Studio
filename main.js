const { app, BrowserWindow, dialog, ipcMain, shell } = require('electron');
const path = require('path');

function createWindow() {
  const win = new BrowserWindow({
    width: 1440,
    height: 900,
    minWidth: 1040,
    minHeight: 720,
    backgroundColor: '#031226',
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
    },
  });

  win.loadFile(path.join(__dirname, 'renderer', 'index.html'));
}

async function selectFile(options) {
  const result = await dialog.showOpenDialog({ properties: ['openFile'], ...options });
  return result.canceled ? '' : result.filePaths[0];
}

ipcMain.handle('shorts:select-video', () => selectFile({
  title: 'Select an authorized source video',
  filters: [{ name: 'Video', extensions: ['mp4', 'mov', 'm4v', 'webm', 'mkv'] }],
}));

ipcMain.handle('shorts:select-transcript', () => selectFile({
  title: 'Select a time-coded transcript',
  filters: [{ name: 'Timed transcript', extensions: ['srt', 'vtt', 'txt'] }],
}));

ipcMain.handle('shorts:select-output', async () => {
  const result = await dialog.showOpenDialog({
    title: 'Select the output folder for separate Shorts files',
    properties: ['openDirectory', 'createDirectory'],
  });
  return result.canceled ? '' : result.filePaths[0];
});

ipcMain.handle('shorts:generate', async (event, input) => {
  const { generateProducedShorts } = await import('./scripts/generate-produced-shorts.mjs');
  return generateProducedShorts(input, (progress) => {
    if (!event.sender.isDestroyed()) event.sender.send('shorts:progress', progress);
  });
});

ipcMain.handle('shorts:open-path', async (_event, targetPath) => {
  if (!targetPath || typeof targetPath !== 'string') return 'No path supplied.';
  return shell.openPath(path.resolve(targetPath));
});

app.whenReady().then(() => {
  createWindow();
  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow();
  });
});

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') app.quit();
});
