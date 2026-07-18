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

  async function choose(target, picker) {
    const selected = await picker();
    if (selected) byId(target).value = selected;
  }

  byId('chooseVideo').addEventListener('click', () => choose('videoPath', window.fgbStudio.selectVideo));
  byId('chooseTranscript').addEventListener('click', () => choose('transcriptPath', window.fgbStudio.selectTranscript));
  byId('chooseOutput').addEventListener('click', () => choose('outputPath', window.fgbStudio.selectOutput));
  byId('openOutput').addEventListener('click', () => latestOutput && window.fgbStudio.openPath(latestOutput));

  window.fgbStudio.onShortsProgress((payload) => {
    message.textContent = payload.message || 'Working…';
    if (payload.stage === 'render' && payload.total) {
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
      input: byId('videoPath').value.trim(),
      transcript: byId('transcriptPath').value.trim(),
      outputDir: byId('outputPath').value.trim(),
      episodeNumber: byId('episodeNumber').value.trim(),
      episodeTitle: byId('episodeTitle').value.trim(),
      project: byId('project').value,
      referenceUrl: byId('referenceUrl').value.trim(),
      limit: Number(byId('limit').value),
      minSeconds: Number(byId('minSeconds').value),
      maxSeconds: Number(byId('maxSeconds').value),
      layout: byId('layout').value,
      watermark: byId('watermark').value.trim(),
      captionColor: '#C83803',
    };

    const missing = [];
    if (!input.episodeTitle) missing.push('episode title');
    if (!input.input) missing.push('source video');
    if (!input.transcript) missing.push('time-coded transcript');
    if (!input.outputDir) missing.push('output folder');
    if (missing.length) {
      showError(`Required: ${missing.join(', ')}.`);
      return;
    }
    if (input.maxSeconds <= input.minSeconds) {
      showError('Maximum seconds must be greater than minimum seconds.');
      return;
    }

    setState('running', 'Producing');
    message.textContent = 'Analyzing transcript and selecting the strongest non-overlapping clips.';
    generateButton.disabled = true;

    try {
      const output = await window.fgbStudio.generateShorts(input);
      latestOutput = output.outputDir;
      setState('complete', 'Complete');
      message.textContent = `Created ${output.shorts.length} separate produced Shorts.`;
      progressBar.style.width = '100%';
      counter.textContent = `${output.shorts.length} / ${output.shorts.length}`;
      byId('resultSummary').textContent = `${output.shorts.length} MP4 files plus separate metadata and caption files.`;

      output.shorts.forEach((item) => {
        const card = document.createElement('article');
        card.className = 'result-item';
        const title = document.createElement('strong');
        title.textContent = `Short ${item.rank}: ${item.title}`;
        const details = document.createElement('span');
        details.textContent = `${item.sourceTimestamp} · ${item.durationSeconds}s · score ${item.score}`;
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
}());
