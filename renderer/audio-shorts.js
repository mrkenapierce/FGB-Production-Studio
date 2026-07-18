(function () {
  const byId = (id) => document.getElementById(id);
  const state = byId('state');
  const message = byId('message');
  const progressBar = byId('progressBar');
  const counter = byId('counter');
  const errorBox = byId('errorBox');
  const results = byId('results');
  const resultList = byId('resultList');
  const generateButton = byId('generate');
  let latestOutput = '';
  let settings = { openaiConfigured: false };

  function setState(name, label) {
    state.className = `state ${name}`;
    state.textContent = label;
  }

  function showError(error) {
    setState('failed', 'Failed');
    errorBox.textContent = error && (error.stack || error.message) ? (error.stack || error.message) : String(error);
    errorBox.classList.remove('hidden');
    generateButton.disabled = false;
  }

  function updateApiStatus() {
    byId('apiStatus').textContent = settings.openaiConfigured
      ? `Configured via ${settings.source}. WAV-only transcription is available.`
      : 'Not configured. Save a key or supply a time-coded transcript.';
    byId('clearKey').disabled = !settings.openaiConfigured || settings.source === 'environment';
  }

  async function refreshSettings() {
    settings = await window.fgbStudio.getAudioShortsSettings();
    updateApiStatus();
  }

  async function choose(target, picker) {
    const selected = await picker();
    if (selected) byId(target).value = selected;
  }

  byId('project').addEventListener('change', () => {
    byId('customRow').classList.toggle('hidden', byId('project').value !== 'custom');
  });
  byId('chooseAudio').addEventListener('click', () => choose('audioPath', window.fgbStudio.selectAudio));
  byId('chooseTranscript').addEventListener('click', () => choose('transcriptPath', window.fgbStudio.selectAudioTranscript));
  byId('chooseVisuals').addEventListener('click', () => choose('visualsPath', window.fgbStudio.selectVisualAssets));
  byId('chooseOutput').addEventListener('click', () => choose('outputPath', window.fgbStudio.selectAudioOutput));
  byId('openOutput').addEventListener('click', () => latestOutput && window.fgbStudio.openPath(latestOutput));

  byId('saveKey').addEventListener('click', async () => {
    try {
      settings = await window.fgbStudio.saveOpenAIKey(byId('apiKey').value);
      byId('apiKey').value = '';
      updateApiStatus();
    } catch (error) {
      showError(error);
    }
  });

  byId('clearKey').addEventListener('click', async () => {
    try {
      settings = await window.fgbStudio.clearOpenAIKey();
      updateApiStatus();
    } catch (error) {
      showError(error);
    }
  });

  window.fgbStudio.onAudioShortsProgress((payload) => {
    message.textContent = payload.message || 'Working…';
    if ((payload.stage === 'render' || payload.stage === 'transcription') && payload.total) {
      const pct = Math.max(2, ((payload.current - 1) / payload.total) * 100);
      progressBar.style.width = `${pct}%`;
      counter.textContent = `${payload.current} / ${payload.total}`;
    } else if (payload.stage === 'render-progress') {
      message.textContent = `Rendering Short ${payload.rank} · ${payload.time}`;
    } else if (payload.stage === 'complete') {
      progressBar.style.width = '100%';
    }
  });

  generateButton.addEventListener('click', async () => {
    errorBox.classList.add('hidden');
    results.classList.add('hidden');
    resultList.innerHTML = '';
    progressBar.style.width = '1%';
    counter.textContent = '0 / 0';

    const input = {
      audio: byId('audioPath').value.trim(),
      transcript: byId('transcriptPath').value.trim(),
      visualAssetsDir: byId('visualsPath').value.trim(),
      outputDir: byId('outputPath').value.trim(),
      episodeNumber: byId('episodeNumber').value.trim(),
      episodeTitle: byId('episodeTitle').value.trim(),
      project: byId('project').value,
      channelName: byId('channelName').value.trim(),
      watermark: byId('watermark').value.trim(),
      referenceUrl: byId('referenceUrl').value.trim(),
      totalShorts: Number(byId('totalShorts').value),
      premiumShorts: Number(byId('premiumShorts').value),
      minSeconds: Number(byId('minSeconds').value),
      maxSeconds: Number(byId('maxSeconds').value),
      captionColor: '#C83803',
    };

    const missing = [];
    if (!input.episodeTitle) missing.push('episode title');
    if (!input.audio) missing.push('WAV audio');
    if (!input.outputDir) missing.push('output folder');
    if (input.project === 'custom' && !input.channelName) missing.push('custom channel name');
    if (missing.length) return showError(`Required: ${missing.join(', ')}.`);
    if (!input.transcript && !settings.openaiConfigured) return showError('Automatic transcription is not configured. Save an OpenAI API key or select a time-coded transcript.');
    if (input.maxSeconds <= input.minSeconds) return showError('Maximum seconds must be greater than minimum seconds.');
    if (input.premiumShorts > input.totalShorts) return showError('Premium slots cannot exceed total Shorts.');

    setState('running', 'Producing');
    message.textContent = input.transcript ? 'Reading the supplied transcript.' : 'Preparing the WAV for automatic transcription.';
    generateButton.disabled = true;

    try {
      const output = await window.fgbStudio.generateAudioShorts(input);
      latestOutput = output.outputDir;
      setState('complete', 'Complete');
      message.textContent = `Created ${output.shorts.length} separate audio-first Shorts.`;
      progressBar.style.width = '100%';
      counter.textContent = `${output.shorts.length} / ${output.shorts.length}`;
      byId('resultSummary').textContent = `${output.shorts.length} MP4 files with separate metadata, captions, and transcript records.`;

      output.shorts.forEach((item) => {
        const card = document.createElement('article');
        card.className = 'result-item';
        const title = document.createElement('strong');
        title.textContent = `Short ${item.rank}: ${item.title}`;
        const tier = document.createElement('span');
        tier.className = 'tier-pill';
        tier.textContent = item.tier;
        title.appendChild(tier);
        const details = document.createElement('div');
        details.className = 'result-meta';
        details.textContent = `${item.sourceTimestamp} · ${item.durationSeconds}s · ${item.visualTreatment}`;
        const actions = document.createElement('div');
        actions.className = 'result-actions';
        const openVideo = document.createElement('button');
        openVideo.className = 'secondary';
        openVideo.textContent = 'Open MP4';
        openVideo.addEventListener('click', () => window.fgbStudio.openPath(item.videoFile));
        const openMetadata = document.createElement('button');
        openMetadata.className = 'secondary';
        openMetadata.textContent = 'Open metadata';
        openMetadata.addEventListener('click', () => window.fgbStudio.openPath(item.metadataFile));
        actions.append(openVideo, openMetadata);
        card.append(title, details, actions);
        resultList.append(card);
      });
      results.classList.remove('hidden');
      generateButton.disabled = false;
    } catch (error) {
      showError(error);
    }
  });

  refreshSettings().catch(showError);
}());
