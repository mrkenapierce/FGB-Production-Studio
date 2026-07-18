const { app, BrowserWindow, dialog, ipcMain, shell, safeStorage } = require('electron');
const path = require('path');
const fs = require('fs/promises');

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

async function selectDirectory(title) {
  const result = await dialog.showOpenDialog({ title, properties: ['openDirectory', 'createDirectory'] });
  return result.canceled ? '' : result.filePaths[0];
}

function settingsPath() {
  return path.join(app.getPath('userData'), 'production-studio-settings.json');
}

async function readSettings() {
  try {
    return JSON.parse(await fs.readFile(settingsPath(), 'utf8'));
  } catch {
    return {};
  }
}

async function writeSettings(settings) {
  await fs.mkdir(path.dirname(settingsPath()), { recursive: true });
  await fs.writeFile(settingsPath(), JSON.stringify(settings, null, 2), 'utf8');
}

async function readOpenAIKey() {
  if (process.env.OPENAI_API_KEY) return process.env.OPENAI_API_KEY;
  const settings = await readSettings();
  if (!settings.openaiApiKeyEncrypted || !safeStorage.isEncryptionAvailable()) return '';
  try {
    return safeStorage.decryptString(Buffer.from(settings.openaiApiKeyEncrypted, 'base64'));
  } catch {
    return '';
  }
}

ipcMain.handle('shorts:select-video', () => selectFile({
  title: 'Select an authorized source video',
  filters: [{ name: 'Video', extensions: ['mp4', 'mov', 'm4v', 'webm', 'mkv'] }],
}));

ipcMain.handle('shorts:select-transcript', () => selectFile({
  title: 'Select a time-coded transcript',
  filters: [{ name: 'Timed transcript', extensions: ['srt', 'vtt', 'txt'] }],
}));

ipcMain.handle('shorts:select-output', () => selectDirectory('Select the output folder for separate Shorts files'));

ipcMain.handle('shorts:generate', async (event, input) => {
  const { generateProducedShorts } = await import('./scripts/generate-produced-shorts.mjs');
  return generateProducedShorts(input, (progress) => {
    if (!event.sender.isDestroyed()) event.sender.send('shorts:progress', progress);
  });
});

ipcMain.handle('audio-shorts:select-audio', () => selectFile({
  title: 'Select the WAV narration or episode audio',
  filters: [{ name: 'WAV audio', extensions: ['wav'] }],
}));

ipcMain.handle('audio-shorts:select-transcript', () => selectFile({
  title: 'Select an optional time-coded transcript',
  filters: [{ name: 'Timed transcript', extensions: ['srt', 'vtt', 'txt'] }],
}));

ipcMain.handle('audio-shorts:select-visuals', () => selectDirectory('Select an optional visual asset folder'));
ipcMain.handle('audio-shorts:select-output', () => selectDirectory('Select the output folder for audio-first Shorts'));

ipcMain.handle('audio-shorts:get-settings', async () => ({
  openaiConfigured: Boolean(await readOpenAIKey()),
  encryptionAvailable: safeStorage.isEncryptionAvailable(),
  source: process.env.OPENAI_API_KEY ? 'environment' : 'encrypted local settings',
}));

ipcMain.handle('audio-shorts:save-api-key', async (_event, apiKey) => {
  const key = String(apiKey || '').trim();
  if (!key) throw new Error('Enter an API key before saving.');
  if (!safeStorage.isEncryptionAvailable()) throw new Error('Secure operating-system encryption is unavailable on this computer. Use OPENAI_API_KEY instead.');
  const settings = await readSettings();
  settings.openaiApiKeyEncrypted = safeStorage.encryptString(key).toString('base64');
  await writeSettings(settings);
  return { openaiConfigured: true, encryptionAvailable: true, source: 'encrypted local settings' };
});

ipcMain.handle('audio-shorts:clear-api-key', async () => {
  const settings = await readSettings();
  delete settings.openaiApiKeyEncrypted;
  await writeSettings(settings);
  return { openaiConfigured: Boolean(process.env.OPENAI_API_KEY), encryptionAvailable: safeStorage.isEncryptionAvailable(), source: process.env.OPENAI_API_KEY ? 'environment' : 'not configured' };
});

ipcMain.handle('audio-shorts:generate', async (event, input) => {
  const { generateAudioFirstShorts } = await import('./scripts/generate-audio-first-shorts.mjs');
  return generateAudioFirstShorts({ ...input, apiKey: await readOpenAIKey() }, (progress) => {
    if (!event.sender.isDestroyed()) event.sender.send('audio-shorts:progress', progress);
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
