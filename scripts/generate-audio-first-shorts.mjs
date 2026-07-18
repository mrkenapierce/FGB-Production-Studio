import fs from 'node:fs/promises';
import path from 'node:path';
import os from 'node:os';
import { spawn } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import sharp from 'sharp';
import {
  buildCandidateWindows,
  formatTimestamp,
  generateWordCaptions,
  parseTranscriptText,
  selectCandidates,
} from './generate-produced-shorts.mjs';

const DEFAULTS = {
  totalShorts: 8,
  premiumShorts: 3,
  minSeconds: 20,
  maxSeconds: 58,
  targetSeconds: 38,
  captionColor: '#C83803',
  captionY: 1240,
  captionFontSize: 150,
  fps: 30,
  transcriptionModel: 'whisper-1',
  chunkSeconds: 900,
};

const CHANNELS = {
  fgb: {
    name: "Football's Greatest Bears",
    brand: 'FGB',
    eyebrow: 'FOOTBALL COMMENTARY',
    hashtags: ['#ChicagoBears', '#BearDown', '#NFL', '#FGB'],
    closing: 'BEAR DOWN AND FGB.',
  },
  fgbars: {
    name: "Football's Greatest Bars",
    brand: 'FGBARS',
    eyebrow: 'FOOTBALL CULTURE',
    hashtags: ['#Football', '#SportsBars', '#FootballFans', '#FGBars'],
    closing: "IF YOU LOVE FOOTBALL, YOU'RE HOME.",
  },
  epic: {
    name: 'EPIC Communities',
    brand: 'EPIC',
    eyebrow: 'COMMUNITY IMPACT',
    hashtags: ['#EPICCommunities', '#CommunityImpact', '#LocalBusiness'],
    closing: 'LOCAL SUPPORT. LASTING IMPACT.',
  },
  custom: {
    name: 'YouTube Channel',
    brand: 'CHANNEL',
    eyebrow: 'EDITORIAL SHORT',
    hashtags: ['#YouTubeShorts'],
    closing: 'WATCH THE FULL EPISODE.',
  },
};

const TACTICAL_TERMS = [
  'formation', 'formations', 'route', 'routes', 'concept', 'concepts', 'scheme', 'schemes',
  'coverage', 'cover 2', 'cover two', 'cover 3', 'cover three', 'man coverage', 'zone coverage',
  'blitz', 'pressure', 'protection', 'offensive line', 'defensive line', 'front seven', 'front',
  'matchup', 'matchups', 'motion', 'play action', 'play-action', 'read option', 'rpo', 'gap',
  'leverage', 'spacing', 'personnel', 'snap', 'quarterback read', 'progression', 'audible',
];

function emit(onProgress, payload) {
  if (typeof onProgress === 'function') onProgress(payload);
  if (process.env.FGB_SHORTS_PROGRESS === '1') console.log(`PROGRESS ${JSON.stringify(payload)}`);
}

function sanitize(value, fallback = 'short') {
  return String(value || fallback)
    .normalize('NFKD')
    .replace(/[^a-zA-Z0-9._-]+/g, '_')
    .replace(/_+/g, '_')
    .replace(/^_|_$/g, '')
    .slice(0, 100) || fallback;
}

function escapeXml(value = '') {
  return String(value).replace(/[&<>"']/g, (character) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#039;',
  }[character]));
}

function escapeFilterText(value) {
  return String(value)
    .replace(/\\/g, '\\\\')
    .replace(/'/g, "\\'")
    .replace(/:/g, '\\:')
    .replace(/,/g, '\\,')
    .replace(/%/g, '\\%')
    .replace(/\[/g, '\\[')
    .replace(/\]/g, '\\]');
}

function escapeFilterPath(value) {
  return String(value).replace(/\\/g, '/').replace(/:/g, '\\:').replace(/'/g, "\\'");
}

function wrapWords(text, maxChars = 19, maxLines = 5) {
  const source = String(text || '').trim().replace(/\s+/g, ' ');
  const sourceWords = source.split(' ').filter(Boolean);
  const lines = [];
  let line = '';
  for (const word of sourceWords) {
    const next = line ? `${line} ${word}` : word;
    if (next.length > maxChars && line) {
      lines.push(line);
      line = word;
    } else {
      line = next;
    }
    if (lines.length >= maxLines) break;
  }
  if (line && lines.length < maxLines) lines.push(line);
  if (sourceWords.join(' ').length > lines.join(' ').length && lines.length) {
    lines[lines.length - 1] = `${lines[lines.length - 1].replace(/[.…]+$/, '')}…`;
  }
  return lines;
}

function sentenceFragments(text) {
  const fragments = String(text || '').split(/(?<=[.!?])\s+/).map((item) => item.trim()).filter(Boolean);
  if (fragments.length >= 3) return fragments;
  const sourceWords = String(text || '').split(/\s+/).filter(Boolean);
  const size = Math.max(8, Math.ceil(sourceWords.length / 4));
  const output = [];
  for (let index = 0; index < sourceWords.length; index += size) output.push(sourceWords.slice(index, index + size).join(' '));
  return output;
}

function tacticalScore(text) {
  const lower = String(text || '').toLowerCase();
  return TACTICAL_TERMS.reduce((score, term) => score + (lower.includes(term) ? 1 : 0), 0);
}

export function assignAudioFirstTiers(candidates, premiumCount = 3) {
  const selected = candidates.map((candidate) => ({ ...candidate, tacticalScore: tacticalScore(candidate.text) }));
  const premium = selected.slice(0, premiumCount);
  const tactical = premium
    .filter((candidate) => candidate.tacticalScore >= 2)
    .sort((a, b) => b.tacticalScore - a.tacticalScore)[0];

  return selected.map((candidate, index) => ({
    ...candidate,
    tier: index >= premiumCount ? 'rapid' : tactical && candidate.rank === tactical.rank ? 'explainer' : 'flagship',
  }));
}

function normalizeWord(word, offset = 0) {
  const text = String(word.word ?? word.text ?? '').trim();
  const start = Number(word.start);
  const end = Number(word.end);
  if (!text || !Number.isFinite(start) || !Number.isFinite(end) || end <= start) return null;
  return { text, start: start + offset, end: end + offset };
}

export function mergeTranscriptionChunks(chunks) {
  const segments = [];
  const words = [];
  for (const chunk of chunks) {
    const offset = Number(chunk.offset) || 0;
    for (const segment of chunk.data?.segments || []) {
      const start = Number(segment.start);
      const end = Number(segment.end);
      const text = String(segment.text || '').trim();
      if (text && Number.isFinite(start) && Number.isFinite(end) && end > start) {
        segments.push({ start: start + offset, end: end + offset, text });
      }
    }
    for (const word of chunk.data?.words || []) {
      const normalized = normalizeWord(word, offset);
      if (normalized) words.push(normalized);
    }
  }
  return {
    text: segments.map((segment) => segment.text).join(' ').replace(/\s+/g, ' ').trim(),
    segments: segments.sort((a, b) => a.start - b.start),
    words: words.sort((a, b) => a.start - b.start),
  };
}

function toSrtTimestamp(seconds) {
  const value = Math.max(0, Number(seconds) || 0);
  const whole = Math.floor(value);
  const ms = Math.round((value - whole) * 1000);
  const hours = Math.floor(whole / 3600);
  const minutes = Math.floor((whole % 3600) / 60);
  const secs = whole % 60;
  return `${String(hours).padStart(2, '0')}:${String(minutes).padStart(2, '0')}:${String(secs).padStart(2, '0')},${String(ms).padStart(3, '0')}`;
}

function transcriptionToSrt(transcription) {
  return transcription.segments.map((segment, index) => [
    index + 1,
    `${toSrtTimestamp(segment.start)} --> ${toSrtTimestamp(segment.end)}`,
    segment.text,
    '',
  ].join('\n')).join('\n');
}

async function firstExisting(paths) {
  for (const candidate of paths.filter(Boolean)) {
    try {
      await fs.access(candidate);
      return candidate;
    } catch {
      // Continue.
    }
  }
  return null;
}

async function resolveFfmpeg() {
  if (process.env.FFMPEG_PATH) return process.env.FFMPEG_PATH;
  try {
    const module = await import('ffmpeg-static');
    if (module.default) return module.default;
  } catch {
    // Use system FFmpeg.
  }
  return process.platform === 'win32' ? 'ffmpeg.exe' : 'ffmpeg';
}

async function resolveFont(explicitFont) {
  const font = await firstExisting([
    explicitFont,
    process.env.CAPTION_FONT_FILE,
    process.platform === 'win32' ? 'C:/Windows/Fonts/impact.ttf' : null,
    process.platform === 'win32' ? 'C:/Windows/Fonts/arialbi.ttf' : null,
    process.platform === 'darwin' ? '/Library/Fonts/Arial Narrow Bold Italic.ttf' : null,
    '/usr/share/fonts/truetype/dejavu/DejaVuSansCondensed-BoldOblique.ttf',
    '/usr/share/fonts/truetype/liberation/LiberationSansNarrow-BoldItalic.ttf',
  ]);
  if (!font) throw new Error('No compatible condensed bold font was found. Set CAPTION_FONT_FILE.');
  return font;
}

function run(command, args, onLine) {
  return new Promise((resolve, reject) => {
    const child = spawn(command, args, { windowsHide: true });
    let stderr = '';
    child.stdout.on('data', (chunk) => onLine?.(chunk.toString()));
    child.stderr.on('data', (chunk) => {
      const text = chunk.toString();
      stderr += text;
      onLine?.(text);
    });
    child.on('error', reject);
    child.on('close', (code) => code === 0
      ? resolve()
      : reject(new Error(`${path.basename(command)} exited with code ${code}. ${stderr.slice(-1600)}`)));
  });
}

async function splitAudioForTranscription(audioFile, workingDir, options, ffmpeg, onProgress) {
  const chunkPattern = path.join(workingDir, 'transcription-%03d.mp3');
  emit(onProgress, { stage: 'transcription-prep', message: 'Preparing WAV audio for transcription.' });
  await run(ffmpeg, [
    '-y', '-i', audioFile,
    '-vn', '-ar', '16000', '-ac', '1', '-b:a', '64k',
    '-f', 'segment', '-segment_time', String(options.chunkSeconds), '-reset_timestamps', '1',
    chunkPattern,
  ]);
  return (await fs.readdir(workingDir))
    .filter((name) => /^transcription-\d+\.mp3$/i.test(name))
    .sort()
    .map((name, index) => ({ file: path.join(workingDir, name), offset: index * options.chunkSeconds }));
}

async function transcribeChunk(file, apiKey, options) {
  const buffer = await fs.readFile(file);
  const form = new FormData();
  form.append('file', new Blob([buffer], { type: 'audio/mpeg' }), path.basename(file));
  form.append('model', options.transcriptionModel);
  form.append('response_format', 'verbose_json');
  form.append('timestamp_granularities[]', 'word');
  form.append('timestamp_granularities[]', 'segment');
  form.append('temperature', '0');
  if (options.transcriptionPrompt) form.append('prompt', options.transcriptionPrompt);

  const response = await fetch('https://api.openai.com/v1/audio/transcriptions', {
    method: 'POST',
    headers: { Authorization: `Bearer ${apiKey}` },
    body: form,
  });
  if (!response.ok) {
    const detail = await response.text();
    throw new Error(`Transcription failed (${response.status}): ${detail.slice(0, 700)}`);
  }
  return response.json();
}

export async function transcribeAudioWithOpenAI(audioFile, apiKey, workingDir, options, onProgress) {
  if (!apiKey) throw new Error('An OpenAI API key is required when no transcript file is supplied.');
  const ffmpeg = await resolveFfmpeg();
  const chunks = await splitAudioForTranscription(audioFile, workingDir, options, ffmpeg, onProgress);
  if (!chunks.length) throw new Error('The WAV file could not be prepared for transcription.');
  const results = [];
  for (let index = 0; index < chunks.length; index += 1) {
    emit(onProgress, {
      stage: 'transcription', current: index + 1, total: chunks.length,
      message: `Transcribing audio section ${index + 1} of ${chunks.length}.`,
    });
    results.push({ offset: chunks[index].offset, data: await transcribeChunk(chunks[index].file, apiKey, options) });
  }
  return mergeTranscriptionChunks(results);
}

async function loadTranscript(options, workingDir, onProgress) {
  if (options.transcript) {
    emit(onProgress, { stage: 'transcript', message: 'Reading supplied time-coded transcript.' });
    const text = await fs.readFile(path.resolve(options.transcript), 'utf8');
    const segments = parseTranscriptText(text);
    if (segments.length < 2) throw new Error('The transcript did not contain usable time-coded cues.');
    return { text: segments.map((segment) => segment.text).join(' '), segments, words: [] };
  }
  return transcribeAudioWithOpenAI(options.audio, options.apiKey, workingDir, options, onProgress);
}

function channelConfig(options) {
  const base = CHANNELS[options.project] || CHANNELS.custom;
  return {
    ...base,
    name: options.channelName || base.name,
    brand: options.watermark || base.brand,
    hashtags: options.hashtags?.length ? options.hashtags : base.hashtags,
  };
}

async function listVisualAssets(directory) {
  if (!directory) return [];
  try {
    const entries = await fs.readdir(path.resolve(directory), { withFileTypes: true });
    return entries
      .filter((entry) => entry.isFile() && /\.(png|jpe?g|webp)$/i.test(entry.name))
      .map((entry) => path.join(path.resolve(directory), entry.name));
  } catch {
    return [];
  }
}

function assetScore(file, candidate) {
  const haystack = path.basename(file).toLowerCase();
  const keywords = String(`${candidate.title} ${candidate.text}`).toLowerCase().match(/[a-z0-9']+/g) || [];
  return [...new Set(keywords.filter((word) => word.length >= 5))]
    .reduce((score, keyword) => score + (haystack.includes(keyword) ? 1 : 0), 0);
}

function pickAssets(assets, candidate, count) {
  return [...assets]
    .sort((a, b) => assetScore(b, candidate) - assetScore(a, candidate) || a.localeCompare(b))
    .slice(0, count);
}

function palette(project) {
  if (project === 'epic') return { dark: '#071323', panel: '#102a3e', accent: '#C83803', secondary: '#E6B566', muted: '#B8C6D5' };
  if (project === 'fgbars') return { dark: '#090B12', panel: '#1A1820', accent: '#C83803', secondary: '#F0B44D', muted: '#C6C2C8' };
  return { dark: '#030A16', panel: '#081B33', accent: '#C83803', secondary: '#F3B33D', muted: '#B8C3D1' };
}

function textLinesSvg(lines, x, startY, size, gap, fill, anchor = 'start', stroke = '#000000') {
  return lines.map((line, index) => `<text x="${x}" y="${startY + index * gap}" text-anchor="${anchor}" fill="${fill}" font-family="Impact, Arial Narrow, Arial, sans-serif" font-size="${size}" font-weight="900" style="paint-order:stroke;stroke:${stroke};stroke-width:5;stroke-linejoin:round">${escapeXml(line.toUpperCase())}</text>`).join('\n');
}

function editorialSvg(candidate, channel, options, sceneIndex, sceneCount) {
  const colors = palette(options.project);
  const fragments = sentenceFragments(candidate.text);
  const fragment = fragments[Math.min(sceneIndex, fragments.length - 1)] || candidate.title;
  const titleLines = wrapWords(sceneIndex === 0 ? candidate.title : fragment, sceneIndex === 0 ? 16 : 21, sceneIndex === 0 ? 5 : 6);
  const number = String(candidate.rank).padStart(2, '0');
  const bars = Array.from({ length: 13 }, (_, index) => `<rect x="${55 + index * 80}" y="${1620 - (index % 4) * 26}" width="46" height="${100 + (index % 5) * 22}" fill="${colors.accent}" opacity="${0.15 + (index % 3) * 0.08}"/>`).join('');
  return `<svg xmlns="http://www.w3.org/2000/svg" width="1080" height="1920" viewBox="0 0 1080 1920">
    <defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="${colors.dark}"/><stop offset="1" stop-color="${colors.panel}"/></linearGradient></defs>
    <rect width="1080" height="1920" fill="url(#g)"/>
    <path d="M0 0H1080V230L0 430Z" fill="${colors.accent}" opacity=".2"/>
    <path d="M1080 0H790L1080 620Z" fill="${colors.secondary}" opacity=".08"/>
    ${bars}
    <rect x="48" y="48" width="984" height="1824" fill="none" stroke="${colors.accent}" stroke-width="5"/>
    <text x="80" y="120" fill="${colors.muted}" font-family="Arial, sans-serif" font-size="28" font-weight="700" letter-spacing="5">${escapeXml(channel.eyebrow)}</text>
    <text x="1000" y="120" text-anchor="end" fill="${colors.accent}" font-family="Impact, Arial Narrow, Arial, sans-serif" font-size="56">${escapeXml(channel.brand)}</text>
    <text x="80" y="230" fill="${colors.secondary}" font-family="Impact, Arial Narrow, Arial, sans-serif" font-size="90">${number}</text>
    <rect x="80" y="270" width="210" height="12" fill="${colors.accent}"/>
    ${textLinesSvg(titleLines, 80, sceneIndex === 0 ? 485 : 430, sceneIndex === 0 ? 112 : 84, sceneIndex === 0 ? 122 : 96, sceneIndex === 0 ? '#F7F4EE' : colors.accent)}
    <rect x="80" y="1260" width="920" height="3" fill="${colors.accent}" opacity=".65"/>
    <text x="80" y="1325" fill="${colors.muted}" font-family="Arial, sans-serif" font-size="27" font-weight="700">${escapeXml(channel.name.toUpperCase())}</text>
    <text x="80" y="1395" fill="#F7F4EE" font-family="Arial, sans-serif" font-size="35" font-weight="700">AUDIO-FIRST EDITORIAL SHORT</text>
    <text x="1000" y="1815" text-anchor="end" fill="${colors.muted}" font-family="Arial, sans-serif" font-size="24">${sceneIndex + 1} / ${sceneCount}</text>
  </svg>`;
}

function explainerSvg(candidate, channel, options, sceneIndex, sceneCount) {
  const colors = palette(options.project);
  const fragments = sentenceFragments(candidate.text);
  const fragment = fragments[Math.min(sceneIndex, fragments.length - 1)] || candidate.title;
  const lines = wrapWords(fragment, 22, 5);
  const arrows = [
    'M170 620 C310 480 430 490 520 650',
    'M520 650 C650 790 770 690 900 530',
    'M210 980 C390 860 650 880 860 1040',
  ].map((d, index) => `<path d="${d}" fill="none" stroke="${index === sceneIndex % 3 ? colors.accent : '#F7F4EE'}" stroke-width="18" stroke-linecap="round" stroke-dasharray="${index === 2 ? '24 20' : '0'}" opacity=".9"/><circle cx="${[520, 900, 860][index]}" cy="${[650, 530, 1040][index]}" r="18" fill="${colors.accent}"/>`).join('');
  const yardLines = Array.from({ length: 11 }, (_, index) => `<line x1="80" x2="1000" y1="${340 + index * 110}" y2="${340 + index * 110}" stroke="#F7F4EE" stroke-width="3" opacity=".13"/>`).join('');
  return `<svg xmlns="http://www.w3.org/2000/svg" width="1080" height="1920" viewBox="0 0 1080 1920">
    <rect width="1080" height="1920" fill="${colors.dark}"/>
    <rect x="48" y="48" width="984" height="1824" rx="18" fill="${colors.panel}" stroke="${colors.accent}" stroke-width="5"/>
    ${yardLines}${arrows}
    <text x="80" y="125" fill="${colors.muted}" font-family="Arial, sans-serif" font-size="28" font-weight="700" letter-spacing="5">TACTICAL EXPLAINER</text>
    <text x="1000" y="125" text-anchor="end" fill="${colors.accent}" font-family="Impact, Arial Narrow, Arial, sans-serif" font-size="54">${escapeXml(channel.brand)}</text>
    <rect x="80" y="1460" width="920" height="320" rx="18" fill="#020712" opacity=".94" stroke="${colors.accent}" stroke-width="4"/>
    ${textLinesSvg(lines, 110, 1555, 62, 68, '#F7F4EE')}
    <text x="970" y="1815" text-anchor="end" fill="${colors.muted}" font-family="Arial, sans-serif" font-size="24">${sceneIndex + 1} / ${sceneCount}</text>
  </svg>`;
}

function rapidSvg(candidate, channel, options, sceneIndex, sceneCount) {
  const colors = palette(options.project);
  const fragments = sentenceFragments(candidate.text);
  const fragment = sceneIndex === sceneCount - 1 ? channel.closing : fragments[Math.min(sceneIndex, fragments.length - 1)] || candidate.title;
  const lines = wrapWords(fragment, 18, 7);
  return `<svg xmlns="http://www.w3.org/2000/svg" width="1080" height="1920" viewBox="0 0 1080 1920">
    <defs><radialGradient id="r"><stop offset="0" stop-color="${colors.panel}"/><stop offset="1" stop-color="${colors.dark}"/></radialGradient></defs>
    <rect width="1080" height="1920" fill="url(#r)"/>
    <circle cx="900" cy="260" r="360" fill="${colors.accent}" opacity=".08"/>
    <circle cx="120" cy="1640" r="430" fill="${colors.secondary}" opacity=".06"/>
    <rect x="50" y="50" width="980" height="1820" fill="none" stroke="${colors.accent}" stroke-width="5"/>
    <text x="80" y="125" fill="${colors.muted}" font-family="Arial, sans-serif" font-size="27" font-weight="700" letter-spacing="5">RAPID COMMENTARY</text>
    <text x="1000" y="125" text-anchor="end" fill="${colors.accent}" font-family="Impact, Arial Narrow, Arial, sans-serif" font-size="54">${escapeXml(channel.brand)}</text>
    <text x="72" y="470" fill="${colors.accent}" font-family="Georgia, serif" font-size="250">“</text>
    ${textLinesSvg(lines, 90, 650, 94, 106, '#F7F4EE')}
    <rect x="90" y="1510" width="410" height="12" fill="${colors.accent}"/>
    <text x="90" y="1585" fill="${colors.muted}" font-family="Arial, sans-serif" font-size="30" font-weight="700">${escapeXml(channel.name.toUpperCase())}</text>
    <text x="990" y="1815" text-anchor="end" fill="${colors.muted}" font-family="Arial, sans-serif" font-size="24">${sceneIndex + 1} / ${sceneCount}</text>
  </svg>`;
}

async function createScene(candidate, channel, options, sceneIndex, sceneCount, outputFile, assetFile) {
  const svg = candidate.tier === 'explainer'
    ? explainerSvg(candidate, channel, options, sceneIndex, sceneCount)
    : candidate.tier === 'rapid'
      ? rapidSvg(candidate, channel, options, sceneIndex, sceneCount)
      : editorialSvg(candidate, channel, options, sceneIndex, sceneCount);

  if (!assetFile || candidate.tier === 'explainer') {
    await sharp(Buffer.from(svg)).png().toFile(outputFile);
    return;
  }
  const overlaySvg = svg.replace(
    /<rect width="1080" height="1920" fill="[^"]+"\/>/,
    '<rect width="1080" height="1920" fill="#020712" opacity=".28"/>',
  );
  const background = await sharp(assetFile)
    .resize(1080, 1920, { fit: 'cover' })
    .modulate({ brightness: 0.48, saturation: 0.7 })
    .blur(candidate.tier === 'rapid' ? 10 : 3)
    .png()
    .toBuffer();
  await sharp(background)
    .composite([
      { input: Buffer.from('<svg xmlns="http://www.w3.org/2000/svg" width="1080" height="1920"><rect width="1080" height="1920" fill="#020712" opacity=".48"/></svg>') },
      { input: Buffer.from(overlaySvg), blend: 'over' },
    ])
    .png()
    .toFile(outputFile);
}

async function renderSceneVideo(sceneFile, outputFile, seconds, options, ffmpeg) {
  const frames = Math.max(1, Math.ceil(seconds * options.fps));
  await run(ffmpeg, [
    '-y', '-loop', '1', '-i', sceneFile, '-t', seconds.toFixed(3),
    '-vf', `scale=1080:1920,zoompan=z='min(zoom+0.0007,1.07)':d=${frames}:s=1080x1920:fps=${options.fps},format=yuv420p`,
    '-an', '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '20', '-r', String(options.fps), outputFile,
  ]);
}

async function concatSceneVideos(files, outputFile, workingDir, ffmpeg) {
  const listFile = path.join(workingDir, `${sanitize(path.basename(outputFile))}.concat.txt`);
  const content = files.map((file) => `file '${String(file).replace(/'/g, "'\\''")}'`).join('\n');
  await fs.writeFile(listFile, content, 'utf8');
  await run(ffmpeg, ['-y', '-f', 'concat', '-safe', '0', '-i', listFile, '-c', 'copy', outputFile]);
}

function captionsForCandidate(transcription, candidate) {
  const exact = transcription.words
    .filter((word) => word.end > candidate.start && word.start < candidate.end)
    .map((word) => ({
      text: word.text,
      start: Math.max(0, word.start - candidate.start),
      end: Math.max(0.04, Math.min(candidate.duration, word.end - candidate.start)),
    }))
    .filter((word) => word.end > word.start);
  if (exact.length) return exact;
  const relevantSegments = transcription.segments.filter((segment) => segment.end > candidate.start && segment.start < candidate.end);
  return generateWordCaptions(relevantSegments, candidate.start, candidate.end);
}

function captionFilter(captions, options, fontFile) {
  let current = '0:v';
  const filters = [];
  captions.forEach((caption, index) => {
    const next = `v${index + 1}`;
    const word = String(caption.text || '').trim().toUpperCase();
    if (!word) return;
    const fontSize = word.length >= 14 ? Math.max(88, options.captionFontSize - (word.length - 13) * 6) : options.captionFontSize;
    filters.push(`[${current}]drawtext=fontfile='${escapeFilterPath(fontFile)}':text='${escapeFilterText(word)}':x=(w-text_w)/2:y=${options.captionY}:fontsize=${fontSize}:fontcolor=${options.captionColor.replace('#', '0x')}:borderw=9:bordercolor=black:shadowx=7:shadowy=7:shadowcolor=black@0.9:enable='between(t,${caption.start.toFixed(3)},${caption.end.toFixed(3)})'[${next}]`);
    current = next;
  });
  filters.push(`[${current}]format=yuv420p[vout]`);
  return filters.join(';\n');
}

function makeDescription(candidate, options, channel) {
  const reference = options.referenceUrl ? `\nWatch the full episode: ${options.referenceUrl}` : '';
  return `${candidate.text.slice(0, 245).trim()}${candidate.text.length > 245 ? '…' : ''}\n\nFrom ${channel.name}: ${options.episodeTitle}.${reference}\n\n${channel.hashtags.join(' ')}`;
}

function makePinnedComment(options, channel) {
  const reference = options.referenceUrl ? `\nFull episode: ${options.referenceUrl}` : '';
  return `What do you think? Add your answer below.${reference}\n\n${channel.closing}`;
}

async function renderCandidate(candidate, transcription, assets, channel, options, outputDir, workingDir, ffmpeg, fontFile, onProgress) {
  const sceneCount = candidate.tier === 'rapid' ? 3 : 5;
  const sceneSeconds = candidate.duration / sceneCount;
  const pickedAssets = pickAssets(assets, candidate, sceneCount);
  const sceneVideos = [];

  for (let index = 0; index < sceneCount; index += 1) {
    emit(onProgress, {
      stage: 'visuals', current: index + 1, total: sceneCount, rank: candidate.rank,
      message: `Building ${candidate.tier} visual ${index + 1} of ${sceneCount} for Short ${candidate.rank}.`,
    });
    const scenePng = path.join(workingDir, `short-${candidate.rank}-scene-${index + 1}.png`);
    const sceneMp4 = path.join(workingDir, `short-${candidate.rank}-scene-${index + 1}.mp4`);
    await createScene(candidate, channel, options, index, sceneCount, scenePng, pickedAssets[index % Math.max(1, pickedAssets.length)]);
    await renderSceneVideo(scenePng, sceneMp4, sceneSeconds, options, ffmpeg);
    sceneVideos.push(sceneMp4);
  }

  const baseVideo = path.join(workingDir, `short-${candidate.rank}-visual-base.mp4`);
  await concatSceneVideos(sceneVideos, baseVideo, workingDir, ffmpeg);
  const captions = captionsForCandidate(transcription, candidate);
  const base = `Short_${String(candidate.rank).padStart(2, '0')}_${candidate.tier}_${sanitize(candidate.title)}`;
  const outputVideo = path.join(outputDir, `${base}.mp4`);
  const filterFile = path.join(workingDir, `${base}.fffilter`);
  await fs.writeFile(filterFile, captionFilter(captions, options, fontFile), 'utf8');

  emit(onProgress, { stage: 'render', current: candidate.rank, total: options.totalShorts, message: `Rendering Short ${candidate.rank} of ${options.totalShorts}.` });
  await run(ffmpeg, [
    '-y', '-i', baseVideo, '-ss', candidate.start.toFixed(3), '-i', options.audio, '-t', candidate.duration.toFixed(3),
    '-filter_complex_script', filterFile, '-map', '[vout]', '-map', '1:a:0',
    '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '19', '-pix_fmt', 'yuv420p',
    '-c:a', 'aac', '-b:a', '192k', '-movflags', '+faststart', '-shortest', outputVideo,
  ], (line) => {
    const time = line.match(/time=(\d{2}:\d{2}:\d{2}(?:\.\d+)?)/)?.[1];
    if (time) emit(onProgress, { stage: 'render-progress', rank: candidate.rank, time });
  });

  const metadata = {
    rank: candidate.rank,
    tier: candidate.tier,
    title: candidate.title,
    episodeNumber: String(options.episodeNumber || ''),
    episodeTitle: options.episodeTitle,
    channel: channel.name,
    referenceUrl: options.referenceUrl || '',
    startSeconds: candidate.start,
    endSeconds: candidate.end,
    durationSeconds: candidate.duration,
    sourceTimestamp: `${formatTimestamp(candidate.start)} – ${formatTimestamp(candidate.end)}`,
    score: candidate.score,
    reasonForSelection: candidate.reasons.join(', '),
    tacticalScore: candidate.tacticalScore,
    transcript: candidate.text,
    description: makeDescription(candidate, options, channel),
    hashtags: channel.hashtags,
    pinnedComment: makePinnedComment(options, channel),
    visualTreatment: candidate.tier === 'flagship'
      ? 'animated sports/editorial newspaper'
      : candidate.tier === 'explainer'
        ? 'automatic tactical diagram explainer'
        : 'rapid quote-driven graphic',
    captionStyle: { oneWordAtATime: true, color: options.captionColor, outline: 'black', position: 'lower-middle safe area' },
    videoFile: outputVideo,
  };
  const metadataFile = path.join(outputDir, `${base}.json`);
  const textFile = path.join(outputDir, `${base}.txt`);
  const captionFile = path.join(outputDir, `${base}.captions.json`);
  await fs.writeFile(metadataFile, JSON.stringify(metadata, null, 2), 'utf8');
  await fs.writeFile(captionFile, JSON.stringify({ oneWordAtATime: true, captions }, null, 2), 'utf8');
  await fs.writeFile(textFile, [
    `TITLE\n${metadata.title}`,
    `\nTIER\n${metadata.tier}`,
    `\nDESCRIPTION\n${metadata.description}`,
    `\nHASHTAGS\n${metadata.hashtags.join(' ')}`,
    `\nPINNED COMMENT\n${metadata.pinnedComment}`,
    `\nSOURCE\n${metadata.sourceTimestamp}`,
  ].join('\n'), 'utf8');
  return { ...metadata, metadataFile, textFile, captionFile };
}

export async function generateAudioFirstShorts(inputOptions, onProgress) {
  const options = { ...DEFAULTS, ...inputOptions };
  options.audio = path.resolve(String(options.audio || ''));
  options.outputDir = path.resolve(String(options.outputDir || ''));
  options.totalShorts = Math.max(1, Math.min(12, Number(options.totalShorts) || DEFAULTS.totalShorts));
  options.premiumShorts = Math.max(0, Math.min(options.totalShorts, Number(options.premiumShorts) || DEFAULTS.premiumShorts));
  options.minSeconds = Math.max(12, Number(options.minSeconds) || DEFAULTS.minSeconds);
  options.maxSeconds = Math.max(options.minSeconds + 5, Math.min(60, Number(options.maxSeconds) || DEFAULTS.maxSeconds));
  options.targetSeconds = Math.min(options.maxSeconds, Math.max(options.minSeconds, Number(options.targetSeconds) || DEFAULTS.targetSeconds));
  options.captionY = Number(options.captionY) || DEFAULTS.captionY;
  options.captionFontSize = Number(options.captionFontSize) || DEFAULTS.captionFontSize;
  options.fps = Number(options.fps) || DEFAULTS.fps;
  options.chunkSeconds = Number(options.chunkSeconds) || DEFAULTS.chunkSeconds;

  if (!inputOptions.audio) throw new Error('A WAV audio file is required.');
  if (!inputOptions.outputDir) throw new Error('An output folder is required.');
  if (!options.episodeTitle) throw new Error('An episode title is required.');
  await fs.access(options.audio);
  await fs.mkdir(options.outputDir, { recursive: true });

  const workingDir = await fs.mkdtemp(path.join(os.tmpdir(), 'fgb-audio-shorts-'));
  const ffmpeg = await resolveFfmpeg();
  const fontFile = await resolveFont(options.fontFile);
  const channel = channelConfig(options);
  options.transcriptionPrompt = options.transcriptionPrompt || `${channel.name}. Preserve proper names, football terminology, business names, locations, and acronyms.`;

  try {
    const transcription = await loadTranscript(options, workingDir, onProgress);
    await fs.writeFile(path.join(options.outputDir, 'audio-first-transcript.json'), JSON.stringify(transcription, null, 2), 'utf8');
    await fs.writeFile(path.join(options.outputDir, 'audio-first-transcript.srt'), transcriptionToSrt(transcription), 'utf8');

    emit(onProgress, { stage: 'analysis', message: 'Selecting three premium and five rapid Shorts.' });
    const candidates = selectCandidates(buildCandidateWindows(transcription.segments, {
      episodeTitle: options.episodeTitle,
      minSeconds: options.minSeconds,
      maxSeconds: options.maxSeconds,
      targetSeconds: options.targetSeconds,
    }), options.totalShorts);
    if (!candidates.length) throw new Error('No viable Short candidates were found in the audio.');
    const tiered = assignAudioFirstTiers(candidates, options.premiumShorts);
    options.totalShorts = tiered.length;
    const assets = await listVisualAssets(options.visualAssetsDir);
    const results = [];
    for (const candidate of tiered) {
      results.push(await renderCandidate(candidate, transcription, assets, channel, options, options.outputDir, workingDir, ffmpeg, fontFile, onProgress));
    }

    const packageBase = `Episode_${sanitize(options.episodeNumber || 'X')}_Audio_First_Shorts`;
    await fs.writeFile(path.join(options.outputDir, `${packageBase}.json`), JSON.stringify(results, null, 2), 'utf8');
    await fs.writeFile(path.join(options.outputDir, `${packageBase}.md`), [
      `# Audio-First Shorts — ${options.episodeTitle}`,
      '',
      `Channel: ${channel.name}`,
      options.referenceUrl ? `Reference video: ${options.referenceUrl}` : '',
      '',
      ...results.flatMap((item) => [
        `## Short ${item.rank}: ${item.title}`,
        `- Tier: ${item.tier}`,
        `- Source: ${item.sourceTimestamp}`,
        `- Duration: ${item.durationSeconds}s`,
        `- Visual treatment: ${item.visualTreatment}`,
        `- File: ${item.videoFile}`,
        '',
      ]),
    ].filter(Boolean).join('\n'), 'utf8');

    emit(onProgress, { stage: 'complete', message: `Created ${results.length} audio-first Shorts.`, outputDir: options.outputDir });
    return { outputDir: options.outputDir, transcriptionSource: options.transcript ? 'supplied' : 'openai', shorts: results };
  } finally {
    if (!options.keepWorkingFiles) await fs.rm(workingDir, { recursive: true, force: true }).catch(() => {});
  }
}

function parseArgs(argv) {
  const args = {};
  for (let index = 0; index < argv.length; index += 1) {
    if (!argv[index].startsWith('--')) continue;
    const key = argv[index].slice(2);
    args[key] = argv[index + 1] && !argv[index + 1].startsWith('--') ? argv[++index] : true;
  }
  return args;
}

const currentFile = fileURLToPath(import.meta.url);
if (process.argv[1] && path.resolve(process.argv[1]) === path.resolve(currentFile)) {
  const args = parseArgs(process.argv.slice(2));
  if (args.help || !args.audio || !args['output-dir'] || !args['episode-title']) {
    console.log(`Usage:\n  npm run generate:audio-shorts -- --audio episode.wav --output-dir outputs/episode --episode-title "Episode title" --episode-number 004 --project fgb --reference-url https://youtu.be/...\n\nOptional: --transcript episode.srt --visual-assets-dir visuals --total-shorts 8 --premium-shorts 3 --api-key OPENAI_KEY`);
    process.exitCode = args.help ? 0 : 1;
  } else {
    process.env.FGB_SHORTS_PROGRESS = '1';
    generateAudioFirstShorts({
      audio: args.audio,
      transcript: args.transcript || '',
      visualAssetsDir: args['visual-assets-dir'] || '',
      outputDir: args['output-dir'],
      episodeTitle: args['episode-title'],
      episodeNumber: args['episode-number'] || '',
      project: args.project || 'fgb',
      channelName: args['channel-name'] || '',
      watermark: args.watermark || '',
      referenceUrl: args['reference-url'] || '',
      totalShorts: args['total-shorts'],
      premiumShorts: args['premium-shorts'],
      apiKey: args['api-key'] || process.env.OPENAI_API_KEY || '',
    }).then((result) => console.log(JSON.stringify(result, null, 2))).catch((error) => {
      console.error(error.stack || error.message);
      process.exit(1);
    });
  }
}
