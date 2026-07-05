const { app, BrowserWindow, ipcMain, dialog } = require('electron');
const path = require('path');

function createWindow() {
  const win = new BrowserWindow({
    width: 1440,
    height: 900,
    backgroundColor: '#031226',
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false
    }
  });

  win.loadFile(path.join(__dirname, 'renderer', 'index.html'));
}

app.whenReady().then(createWindow);

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') app.quit();
});

ipcMain.handle('render-countdown', async (_event, settings) => {
  const save = await dialog.showSaveDialog({
    title: 'Save countdown MP4',
    defaultPath: settings.defaultName || 'FGB_Countdown.mp4',
    filters: [{ name: 'MP4 Video', extensions: ['mp4'] }]
  });

  if (save.canceled || !save.filePath) {
    return { ok: false, canceled: true };
  }

  return {
    ok: false,
    path: save.filePath,
    message: 'Render path selected. MP4 rendering engine will be connected in the next build.'
  };
});
