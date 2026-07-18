import fs from 'node:fs/promises';
import path from 'node:path';
import { spawn } from 'node:child_process';
import { fileURLToPath } from 'node:url';

const DEFAULTS = {
  limit: 8,
  minSeconds: 20,
  maxSeconds: 58,
  targetSeconds: 38,
  layout: 'blur',
  captionColor: '#C83803',
  captionY: 1240,
  captionFontSize: 150,
  watermark: 'FGB',
  fps: 30,
};

const PROJECT_CONFIG = {
  fgb: {
    series: "Football's Greatest Bears",
    hashtags: ['#ChicagoBears', '#BearDown', '#NFL', '#FGB'],
    watermark: 'FGB',
  },
  fgbars: {
    series: "Football's Greatest Bars",
    hashtags: ['#Football', '#SportsBars', '#FootballFans', '#FGBars'],
    watermark: 'FGBARS',
  },
  epic: {
    series: 'EPIC Communities',
    hashtags: ['#EPICCommunities', '#CommunityImpact', '#LocalBusiness'],
    watermark: 'EPIC',
  },
};

const HOOK_PATTERNS = [
  /^(what if|why|how|here(?:'s| is)|the truth|nobody|everyone|imagine|this is|the biggest|the most important)/i,
  /\b(nobody talks about|changes everything|the real question|the problem is|the difference is|you need to understand)\b/i,
];

const CONTRAST_TERMS = [
  'but', 'however', 'instead', 'because', 'the difference', 'the problem', 'the truth',
  'not', "isn't", "doesn't", "can't", 'versus', 'compared with', 'on the other hand',
];

const FILLER_TERMS = new Set([
  'um', 'uh', 'like', 'you know', 'i mean', 'basically', 'actually', 'literally',
  'sort of', 'kind of', 'okay', 'right', 'so yeah',
]);

function emit(onProgress, payload) {
  if (typeof onProgress === 'function') onProgress(payload);
  if (process.env.FGB_SHORTS_PROGRESS === '1') {
    console.log(`PROGRESS ${JSON.stringify(payload)}`);
  }
}

export function parseTimestamp(value) {
  const normalized = String(value || '').trim().replace(',', '.');
  const parts = normalized.split(':').map(Number);
  if (parts.some((part) => !Number.isFinite(part))) {
    throw new Error(`Invalid timestamp: ${value}`);
  }
  if (parts.length === 2) return parts[0] * 60 + parts[1];
  if (parts.length === 3) return parts[0] * 3600 + parts[1] * 60 + parts[2];
  throw new Error(`Invalid timestamp: ${value}`);
}

export function formatTimestamp(totalSeconds, milliseconds = false) {
  const seconds = Math.max(0, Number(totalSeconds) || 0);
  const whole = Math.floor(seconds);
  const ms = Math.round((seconds - whole) * 1000);
  const h = Math.floor(whole / 3600);
  const m = Math.floor((whole % 3600) / 60);
  const s = whole % 60;
  const base = h > 0
    ? `${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`
    : `${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`;
  return milliseconds ? `${base}.${String(ms).padStart(3, '0')}` : base;
}

function decodeEntities(text) {
  return String(text)
    .replace(/&amp;/g, '&')
    .replace(/&lt;/g, '<')
    .replace(/&gt;/g, '>')
    .replace(/&quot;/g, '"')
    .replace(/&#39;/g, "'")
    .replace(/&nbsp;/g, ' ');
}

function cleanCueText(text) {
  return decodeEntities(String(text || ''))
    .replace(/<[^>]+>/g, ' ')
    .replace(/\{\\[^}]+\}/g, ' ')
    .replace(/\[(music|applause|laughter|silence)\]/gi, ' ')
    .replace(/\([^)]*(music|applause|laughter)[^)]*\)/gi, ' ')
    .replace(/^[-–—]\s*/, '')
    .replace(/\s+/g, ' ')
    .trim();
}

function parseTimedBlocks(text) {
  const lines = String(text || '').replace(/^\uFEFF/, '').split(/\r?\n/);
  const cues = [];
  const timing = /^\s*((?:\d{1,2}:)?\d{1,2}:\d{2}(?:[.,]\d{1,3})?)\s*(?:-->|[-–—])\s*((?:\d{1,2}:)?\d{1,2}:\d{2}(?:[.,]\d{1,3})?)(?:\s+.*)?$/;

  for (let i = 0; i < lines.length; i += 1) {
    const match = lines[i].match(timing);
    if (!match) continue;
    const start = parseTimestamp(match[1]);
    const end = parseTimestamp(match[2]);
    const body = [];
    for (i += 1; i < lines.length && lines[i].trim() !== ''; i += 1) {
      if (!/^\d+$/.test(lines[i].trim())) body.push(lines[i]);
    }
    const cueText = cleanCueText(body.join(' '));
    if (cueText && end > start) cues.push({ start, end, text: cueText });
  }

  return cues;
}

function parseInlineTimedText(text) {
  const lines = String(text || '').replace(/^\uFEFF/, '').split(/\r?\n/);
  const cues = [];
  const inline = /^\s*((?:\d{1,2}:)?\d{1,2}:\d{2}(?:[.,]\d{1,3})?)\s*[-–—]\s*((?:\d{1,2}:)?\d{1,2}:\d{2}(?:[.,]\d{1,3})?)\s*[:\-]?\s*(.*)$/;
  for (const line of lines) {
    const match = line.match(inline);
    if (!match) continue;
    const start = parseTimestamp(match[1]);
    const end = parseTimestamp(match[2]);
    const cueText = cleanCueText(match[3]);
    if (cueText && end > start) cues.push({ start, end, text: cueText });
  }
  return cues;
}

export function parseTranscriptText(text) {
  let cues = parseTimedBlocks(text);
  if (cues.length === 0) cues = parseInlineTimedText(text);
  cues = cues
    .filter((cue) => cue.end > cue.start && cue.text)
    .sort((a, b) => a.start - b.start);

  const normalized = [];
  for (const cue of cues) {
    const previous = normalized.at(-1);
    if (previous && Math.abs(previous.start - cue.start) < 0.02 && previous.text === cue.text) continue;
    normalized.push(cue);
  }
  return normalized;
}

function words(text) {
  return String(text || '').toLowerCase().match(/[a-z0-9']+/g) || [];
}

function sentenceEnd(text) {
  return /[.!?]["')\]]?$/.test(String(text || '').trim());
}

function makeTitle(text, fallback) {
  const cleaned = cleanCueText(text)
    .replace(/^(and|but|so|because|also|then|well)\s+/i, '')
    .trim();
  const first = cleaned.split(/(?<=[.!?])\s+/)[0] || cleaned;
  const title = first.replace(/[.!]+$/, '').trim();
  if (!title) return fallback;
  return title.length > 72 ? `${title.slice(0, 69).trim()}…` : title;
}

function extractKeywords(title, extra = []) {
  const stop = new Set(['the', 'and', 'for', 'with', 'that', 'this', 'from', 'are', 'was', 'will', 'can', 'you', 'your', 'about', 'into']);
  return [...new Set([...words(title), ...extra.map((item) => item.toLowerCase())])]
    .filter((word) => word.length >= 4 && !stop.has(word));
}

function fillerRatio(text) {
  const lower = ` ${String(text).toLowerCase()} `;
  let hits = 0;
  for (const term of FILLER_TERMS) {
    const pattern = new RegExp(`\\b${term.replace(/\s+/g, '\\s+')}\\b`, 'g');
    hits += (lower.match(pattern) || []).length;
  }
  return hits / Math.max(1, words(text).length);
}

function scoreWindow(window, options) {
  const { text, duration, firstText, lastText } = window;
  const reasons = [];
  let score = 100 - Math.abs(duration - options.targetSeconds) * 1.25;
  const wordCount = words(text).length;

  if (duration >= 25 && duration <= 48) {
    score += 16;
    reasons.push('strong short-form duration');
  }
  if (wordCount >= 45 && wordCount <= 150) {
    score += 10;
    reasons.push('clear speaking density');
  }

  const hookHits = HOOK_PATTERNS.filter((pattern) => pattern.test(firstText)).length;
  if (hookHits) {
    score += hookHits * 14;
    reasons.push('strong opening hook');
  }

  const questions = (text.match(/\?/g) || []).length;
  if (questions) {
    score += Math.min(questions, 2) * 7;
    reasons.push('contains a question');
  }

  const lower = text.toLowerCase();
  const contrastHits = CONTRAST_TERMS.filter((term) => lower.includes(term)).length;
  if (contrastHits) {
    score += Math.min(contrastHits, 4) * 3;
    reasons.push('contains contrast or tension');
  }

  const keywordHits = options.keywords.filter((keyword) => lower.includes(keyword)).length;
  if (keywordHits) {
    score += Math.min(keywordHits, 5) * 4;
    reasons.push('matches episode subjects');
  }

  if (sentenceEnd(lastText)) {
    score += 12;
    reasons.push('ends on a complete thought');
  } else {
    score -= 12;
    reasons.push('ending may need review');
  }

  if (/^(and|but|so|because|also|then|well|it|they|he|she|this|that)\b/i.test(firstText.trim())) {
    score -= 13;
    reasons.push('opening depends on prior context');
  }

  const filler = fillerRatio(text);
  if (filler > 0.035) {
    score -= Math.min(18, filler * 180);
    reasons.push('contains filler language');
  }

  if (wordCount < 30) score -= 22;
  if (wordCount > 190) score -= 18;

  return { score: Math.round(score * 10) / 10, reasons };
}

export function buildCandidateWindows(cues, inputOptions = {}) {
  const options = {
    ...DEFAULTS,
    ...inputOptions,
  };
  options.keywords = extractKeywords(options.episodeTitle || '', options.keywords || []);
  const windows = [];

  for (let startIndex = 0; startIndex < cues.length; startIndex += 1) {
    let bestForStart = null;
    for (let endIndex = startIndex; endIndex < cues.length; endIndex += 1) {
      const start = cues[startIndex].start;
      const end = cues[endIndex].end;
      const duration = end - start;
      if (duration > options.maxSeconds) break;
      if (duration < options.minSeconds) continue;

      const selected = cues.slice(startIndex, endIndex + 1);
      const text = selected.map((cue) => cue.text).join(' ').replace(/\s+/g, ' ').trim();
      const firstText = selected[0]?.text || '';
      const lastText = selected.at(-1)?.text || '';
      const scored = scoreWindow({ text, duration, firstText, lastText }, options);
      const candidate = {
        start,
        end,
        duration: Math.round(duration * 1000) / 1000,
        text,
        title: makeTitle(text, `Short at ${formatTimestamp(start)}`),
        score: scored.score,
        reasons: scored.reasons,
        cueStartIndex: startIndex,
        cueEndIndex: endIndex,
      };
      if (!bestForStart || candidate.score > bestForStart.score) bestForStart = candidate;
    }
    if (bestForStart) windows.push(bestForStart);
  }

  return windows.sort((a, b) => b.score - a.score || a.start - b.start);
}

function overlapRatio(a, b) {
  const overlap = Math.max(0, Math.min(a.end, b.end) - Math.max(a.start, b.start));
  return overlap / Math.max(1, Math.min(a.duration, b.duration));
}

function jaccard(aText, bText) {
  const a = new Set(words(aText).filter((word) => word.length > 3));
  const b = new Set(words(bText).filter((word) => word.length > 3));
  if (!a.size || !b.size) return 0;
  const intersection = [...a].filter((word) => b.has(word)).length;
  const union = new Set([...a, ...b]).size;
  return intersection / union;
}

export function selectCandidates(candidates, limit = DEFAULTS.limit) {
  const selected = [];
  for (const candidate of candidates) {
    const conflicts = selected.some((existing) =>
      overlapRatio(existing, candidate) > 0.12 || jaccard(existing.text, candidate.text) > 0.64,
    );
    if (conflicts) continue;
    selected.push(candidate);
    if (selected.length >= limit) break;
  }

  if (selected.length < limit) {
    for (const candidate of candidates) {
      if (selected.includes(candidate)) continue;
      if (selected.some((existing) => overlapRatio(existing, candidate) > 0.55)) continue;
      selected.push(candidate);
      if (selected.length >= limit) break;
    }
  }

  return selected.map((candidate, index) => ({ ...candidate, rank: index + 1 }));
}

function wordTokens(text) {
  return cleanCueText(text)
    .split(/\s+/)
    .map((token) => token.trim())
    .filter(Boolean);
}

export function generateWordCaptions(cues, clipStart, clipEnd) {
  const captions = [];
  for (const cue of cues) {
    const start = Math.max(cue.start, clipStart);
    const end = Math.min(cue.end, clipEnd);
    if (end <= start) continue;
    const tokens = wordTokens(cue.text);
    if (!tokens.length) continue;
    const weights = tokens.map((token) => Math.max(1, token.replace(/[^a-z0-9]/gi, '').length));
    const totalWeight = weights.reduce((sum, value) => sum + value, 0);
    let cursor = start;
    tokens.forEach((token, index) => {
      const remaining = end - cursor;
      const rawDuration = (end - start) * (weights[index] / totalWeight);
      const duration = index === tokens.length - 1 ? remaining : Math.max(0.07, rawDuration);
      const wordEnd = Math.min(end, cursor + duration);
      if (wordEnd > cursor) {
        captions.push({
          text: token,
          start: Math.max(0, cursor - clipStart),
          end: Math.max(0.02, wordEnd - clipStart),
        });
      }
      cursor = wordEnd;
    });
  }

  captions.sort((a, b) => a.start - b.start);
  for (let i = 1; i < captions.length; i += 1) {
    if (captions[i].start < captions[i - 1].end) captions[i - 1].end = captions[i].start;
  }
  return captions.filter((caption) => caption.end > caption.start);
}

function sanitizeFileName(value) {
  return String(value || 'short')
    .normalize('NFKD')
    .replace(/[^a-zA-Z0-9._-]+/g, '_')
    .replace(/_+/g, '_')
    .replace(/^_|_$/g, '')
    .slice(0, 100) || 'short';
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

async function resolveFont(explicitFont) {
  const candidates = [
    explicitFont,
    process.env.CAPTION_FONT_FILE,
    process.platform === 'win32' ? 'C:/Windows/Fonts/impact.ttf' : null,
    process.platform === 'win32' ? 'C:/Windows/Fonts/arialbi.ttf' : null,
    process.platform === 'darwin' ? '/Library/Fonts/Arial Narrow Bold Italic.ttf' : null,
    '/usr/share/fonts/truetype/dejavu/DejaVuSansCondensed-BoldOblique.ttf',
    '/usr/share/fonts/truetype/liberation/LiberationSansNarrow-BoldItalic.ttf',
  ];
  const font = await firstExisting(candidates);
  if (!font) throw new Error('No compatible caption font was found. Set CAPTION_FONT_FILE.');
  return font;
}

function ffmpegColor(value, fallback) {
  const color = String(value || fallback).trim();
  return color.startsWith('#') ? `0x${color.slice(1)}` : color;
}

function buildVideoFilter(candidate, captions, options, fontFile) {
  const parts = [];
  if (options.layout === 'crop') {
    parts.push('[0:v]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,fps=' + options.fps + '[v0]');
  } else {
    parts.push('[0:v]split=2[bg][fg]');
    parts.push('[bg]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,boxblur=24:12[bgv]');
    parts.push('[fg]scale=1080:1920:force_original_aspect_ratio=decrease[fgv]');
    parts.push(`[bgv][fgv]overlay=(W-w)/2:(H-h)/2,fps=${options.fps}[v0]`);
  }

  let current = 'v0';
  let index = 1;
  const watermark = String(options.watermark || '').trim();
  if (watermark) {
    const next = `v${index++}`;
    parts.push(
      `[${current}]drawtext=fontfile='${escapeFilterPath(fontFile)}':text='${escapeFilterText(watermark)}':` +
      `x=w-text_w-52:y=48:fontsize=54:fontcolor=white@0.82:borderw=3:bordercolor=black@0.8:` +
      `shadowx=3:shadowy=3:shadowcolor=black@0.8[${next}]`,
    );
    current = next;
  }

  const captionColor = ffmpegColor(options.captionColor, DEFAULTS.captionColor);
  for (const caption of captions) {
    const next = `v${index++}`;
    const cleanWord = caption.text.toUpperCase();
    const fontSize = cleanWord.length >= 14
      ? Math.max(92, options.captionFontSize - (cleanWord.length - 13) * 6)
      : options.captionFontSize;
    parts.push(
      `[${current}]drawtext=fontfile='${escapeFilterPath(fontFile)}':text='${escapeFilterText(cleanWord)}':` +
      `x=(w-text_w)/2:y=${options.captionY}:fontsize=${fontSize}:fontcolor=${captionColor}:` +
      `borderw=9:bordercolor=black:shadowx=7:shadowy=7:shadowcolor=black@0.9:` +
      `enable='between(t,${caption.start.toFixed(3)},${caption.end.toFixed(3)})'[${next}]`,
    );
    current = next;
  }

  parts.push(`[${current}]format=yuv420p[vout]`);
  return parts.join(';\n');
}

function run(command, args, onLine) {
  return new Promise((resolve, reject) => {
    const child = spawn(command, args, { windowsHide: true });
    let stderr = '';
    child.stdout.on('data', (chunk) => {
      const text = chunk.toString();
      onLine?.(text);
    });
    child.stderr.on('data', (chunk) => {
      const text = chunk.toString();
      stderr += text;
      onLine?.(text);
    });
    child.on('error', reject);
    child.on('close', (code) => {
      if (code === 0) resolve();
      else reject(new Error(`FFmpeg exited with code ${code}. ${stderr.slice(-1200)}`));
    });
  });
}

function buildDescription(candidate, options, config) {
  const source = options.referenceUrl ? `\nFull episode: ${options.referenceUrl}` : '';
  return `${candidate.text.slice(0, 240).trim()}${candidate.text.length > 240 ? '…' : ''}\n\n` +
    `From ${config.series}: ${options.episodeTitle}.${source}\n\n${config.hashtags.join(' ')}`;
}

function buildPinnedComment(options) {
  const link = options.referenceUrl ? `\nWatch the full episode: ${options.referenceUrl}` : '';
  const close = options.project === 'fgb'
    ? 'Bear Down and FGB.'
    : options.project === 'fgbars'
      ? "If you love football, you're home."
      : 'Support local businesses. Strengthen local communities.';
  return `What do you think? Add your answer below.${link}\n\n${close}`;
}

async function writeMetadata(outputDir, candidate, metadata) {
  const base = `Short_${String(candidate.rank).padStart(2, '0')}_${sanitizeFileName(candidate.title)}`;
  await fs.writeFile(path.join(outputDir, `${base}.json`), JSON.stringify(metadata, null, 2), 'utf8');
  await fs.writeFile(
    path.join(outputDir, `${base}.txt`),
    [
      `TITLE\n${metadata.title}`,
      `\nDESCRIPTION\n${metadata.description}`,
      `\nHASHTAGS\n${metadata.hashtags.join(' ')}`,
      `\nPINNED COMMENT\n${metadata.pinnedComment}`,
      `\nSOURCE\n${metadata.sourceTimestamp}`,
    ].join('\n'),
    'utf8',
  );
  return base;
}

async function resolveFfmpeg() {
  if (process.env.FFMPEG_PATH) return process.env.FFMPEG_PATH;
  try {
    const module = await import('ffmpeg-static');
    if (module.default) return module.default;
  } catch {
    // Fall through to system FFmpeg for development and CI environments.
  }
  return process.platform === 'win32' ? 'ffmpeg.exe' : 'ffmpeg';
}

export async function generateProducedShorts(inputOptions, onProgress) {
  const ffmpeg = await resolveFfmpeg();
  const options = { ...DEFAULTS, ...inputOptions };
  const projectConfig = PROJECT_CONFIG[options.project] || PROJECT_CONFIG.fgb;
  options.watermark = options.watermark || projectConfig.watermark;
  options.limit = Math.max(1, Math.min(12, Number(options.limit) || DEFAULTS.limit));
  options.minSeconds = Math.max(10, Number(options.minSeconds) || DEFAULTS.minSeconds);
  options.maxSeconds = Math.max(options.minSeconds + 5, Number(options.maxSeconds) || DEFAULTS.maxSeconds);
  options.targetSeconds = Math.min(options.maxSeconds, Math.max(options.minSeconds, Number(options.targetSeconds) || DEFAULTS.targetSeconds));
  options.captionY = Number(options.captionY) || DEFAULTS.captionY;
  options.captionFontSize = Number(options.captionFontSize) || DEFAULTS.captionFontSize;
  options.fps = Number(options.fps) || DEFAULTS.fps;

  if (!options.input) throw new Error('A source video is required.');
  if (!options.transcript) throw new Error('A time-coded SRT, VTT, or TXT transcript is required.');
  if (!options.outputDir) throw new Error('An output directory is required.');
  if (!options.episodeTitle) throw new Error('An episode title is required.');

  const input = path.resolve(options.input);
  const transcriptFile = path.resolve(options.transcript);
  const outputDir = path.resolve(options.outputDir);
  await fs.access(input);
  await fs.access(transcriptFile);
  await fs.mkdir(outputDir, { recursive: true });

  emit(onProgress, { stage: 'transcript', message: 'Reading time-coded transcript.' });
  const transcriptText = await fs.readFile(transcriptFile, 'utf8');
  const cues = parseTranscriptText(transcriptText);
  if (cues.length < 2) {
    throw new Error('No usable time-coded cues were found. Supply an SRT, VTT, or timestamped TXT transcript.');
  }

  emit(onProgress, { stage: 'analysis', message: `Analyzing ${cues.length} transcript cues.` });
  const candidates = selectCandidates(buildCandidateWindows(cues, options), options.limit);
  if (!candidates.length) throw new Error('No viable Shorts candidates were found in the requested duration range.');

  const fontFile = await resolveFont(options.fontFile);
  const packageRecords = [];
  for (const candidate of candidates) {
    emit(onProgress, {
      stage: 'render',
      current: candidate.rank,
      total: candidates.length,
      message: `Rendering Short ${candidate.rank} of ${candidates.length}: ${candidate.title}`,
    });

    const relevantCues = cues.filter((cue) => cue.end > candidate.start && cue.start < candidate.end);
    const captions = generateWordCaptions(relevantCues, candidate.start, candidate.end);
    const metadata = {
      rank: candidate.rank,
      title: candidate.title,
      episodeNumber: String(options.episodeNumber || ''),
      episodeTitle: options.episodeTitle,
      project: options.project || 'fgb',
      referenceUrl: options.referenceUrl || '',
      startSeconds: candidate.start,
      endSeconds: candidate.end,
      durationSeconds: candidate.duration,
      sourceTimestamp: `${formatTimestamp(candidate.start)} – ${formatTimestamp(candidate.end)}`,
      score: candidate.score,
      reasonForSelection: candidate.reasons.join(', '),
      transcript: candidate.text,
      description: buildDescription(candidate, options, projectConfig),
      hashtags: projectConfig.hashtags,
      pinnedComment: buildPinnedComment(options),
      captionStyle: {
        oneWordAtATime: true,
        color: options.captionColor,
        outlineColor: '#000000',
        placement: 'lower-middle safe area',
      },
    };

    const base = await writeMetadata(outputDir, candidate, metadata);
    const outputFile = path.join(outputDir, `${base}.mp4`);
    const captionFile = path.join(outputDir, `${base}.captions.json`);
    const filterFile = path.join(outputDir, `${base}.fffilter`);
    await fs.writeFile(captionFile, JSON.stringify({ oneWordAtATime: true, captions }, null, 2), 'utf8');
    await fs.writeFile(filterFile, buildVideoFilter(candidate, captions, options, fontFile), 'utf8');

    const duration = Math.max(0.1, candidate.end - candidate.start);
    const args = [
      '-y',
      '-ss', candidate.start.toFixed(3),
      '-i', input,
      '-t', duration.toFixed(3),
      '-filter_complex_script', filterFile,
      '-map', '[vout]',
      '-map', '0:a?',
      '-c:v', 'libx264',
      '-preset', 'veryfast',
      '-crf', '19',
      '-pix_fmt', 'yuv420p',
      '-c:a', 'aac',
      '-b:a', '192k',
      '-movflags', '+faststart',
      '-shortest',
      outputFile,
    ];
    await run(ffmpeg, args, (line) => {
      const time = line.match(/time=(\d{2}:\d{2}:\d{2}(?:\.\d+)?)/)?.[1];
      if (time) emit(onProgress, { stage: 'render-progress', rank: candidate.rank, time });
    });

    packageRecords.push({ ...metadata, videoFile: outputFile, metadataFile: path.join(outputDir, `${base}.json`) });
  }

  const packageName = `Episode_${sanitizeFileName(options.episodeNumber || 'X')}_Produced_Shorts`;
  await fs.writeFile(path.join(outputDir, `${packageName}.json`), JSON.stringify(packageRecords, null, 2), 'utf8');
  await fs.writeFile(
    path.join(outputDir, `${packageName}.md`),
    [
      `# Produced Shorts — ${options.episodeTitle}`,
      '',
      options.referenceUrl ? `Reference video: ${options.referenceUrl}` : '',
      '',
      ...packageRecords.flatMap((item) => [
        `## Short ${item.rank}: ${item.title}`,
        `- Source: ${item.sourceTimestamp}`,
        `- Duration: ${item.durationSeconds}s`,
        `- Score: ${item.score}`,
        `- Why: ${item.reasonForSelection}`,
        `- File: ${item.videoFile}`,
        '',
      ]),
    ].filter(Boolean).join('\n'),
    'utf8',
  );

  emit(onProgress, { stage: 'complete', message: `Created ${packageRecords.length} produced Shorts.`, outputDir });
  return { outputDir, shorts: packageRecords };
}

function parseArgs(argv) {
  const args = {};
  for (let i = 0; i < argv.length; i += 1) {
    const token = argv[i];
    if (!token.startsWith('--')) continue;
    const key = token.slice(2);
    const value = argv[i + 1] && !argv[i + 1].startsWith('--') ? argv[++i] : true;
    args[key] = value;
  }
  return args;
}

function usage() {
  return `Usage:\n  npm run generate:shorts -- \\\n    --input <episode.mp4> \\\n    --transcript <episode.srt|vtt|txt> \\\n    --output-dir <folder> \\\n    --episode-number 004 \\\n    --episode-title "Episode title" \\\n    --project fgb \\\n    --reference-url https://youtu.be/...\n\nOptional: --limit 8 --min-seconds 20 --max-seconds 58 --layout blur|crop --watermark FGB`;
}

const currentFile = fileURLToPath(import.meta.url);
if (process.argv[1] && path.resolve(process.argv[1]) === path.resolve(currentFile)) {
  const args = parseArgs(process.argv.slice(2));
  if (args.help || !args.input || !args.transcript || !args['output-dir']) {
    console.log(usage());
    process.exitCode = args.help ? 0 : 1;
  } else {
    process.env.FGB_SHORTS_PROGRESS = '1';
    generateProducedShorts({
      input: args.input,
      transcript: args.transcript,
      outputDir: args['output-dir'],
      episodeNumber: args['episode-number'] || '',
      episodeTitle: args['episode-title'] || 'Untitled Episode',
      project: args.project || 'fgb',
      referenceUrl: args['reference-url'] || '',
      limit: args.limit,
      minSeconds: args['min-seconds'],
      maxSeconds: args['max-seconds'],
      targetSeconds: args['target-seconds'],
      layout: args.layout || 'blur',
      watermark: args.watermark || '',
      fontFile: args.font || '',
      captionColor: args['caption-color'] || DEFAULTS.captionColor,
    }).then((result) => {
      console.log(JSON.stringify(result, null, 2));
    }).catch((error) => {
      console.error(error.stack || error.message);
      process.exit(1);
    });
  }
}
