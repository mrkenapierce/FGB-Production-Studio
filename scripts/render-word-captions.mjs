import fs from 'node:fs/promises';
import path from 'node:path';
import { spawn } from 'node:child_process';
import ffmpeg from 'ffmpeg-static';

const ROOT = process.cwd();

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
  return [
    'Usage:',
    '  node scripts/render-word-captions.mjs \\',
    '    --input <video.mp4> \\',
    '    --captions <captions.json> \\',
    '    --output <captioned-video.mp4>',
    '',
    'Optional:',
    '  --clip-start <seconds>',
    '  --clip-duration <seconds>',
    '  --font <font-file-path>'
  ].join('\n');
}

function asNumber(value, fallback, label) {
  if (value === undefined || value === null || value === '') return fallback;
  const number = Number(value);
  if (!Number.isFinite(number)) throw new Error(`${label} must be a valid number.`);
  return number;
}

function ffmpegColor(value, fallback) {
  const color = String(value || fallback).trim();
  return color.startsWith('#') ? `0x${color.slice(1)}` : color;
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
  return String(value)
    .replace(/\\/g, '/')
    .replace(/:/g, '\\:')
    .replace(/'/g, "\\'");
}

async function firstExisting(paths) {
  for (const candidate of paths.filter(Boolean)) {
    try {
      await fs.access(candidate);
      return candidate;
    } catch {
      // Try the next candidate.
    }
  }
  return null;
}

async function resolveFont(explicitFont, configuredFont) {
  const candidates = [
    explicitFont,
    process.env.CAPTION_FONT_FILE,
    configuredFont,
    process.platform === 'win32' ? 'C:/Windows/Fonts/impact.ttf' : null,
    process.platform === 'win32' ? 'C:/Windows/Fonts/arialbi.ttf' : null,
    process.platform === 'darwin' ? '/Library/Fonts/Arial Narrow Bold Italic.ttf' : null,
    '/usr/share/fonts/truetype/dejavu/DejaVuSansCondensed-BoldOblique.ttf',
    '/usr/share/fonts/truetype/liberation/LiberationSansNarrow-BoldItalic.ttf'
  ];

  const font = await firstExisting(candidates);
  if (!font) {
    throw new Error('No compatible condensed bold font was found. Set --font or CAPTION_FONT_FILE.');
  }
  return font;
}

function validateCaptions(captions, oneWordAtATime) {
  if (!Array.isArray(captions) || captions.length === 0) {
    throw new Error('The caption file must include a non-empty captions array.');
  }

  const normalized = captions.map((entry, index) => {
    const text = String(entry.text || '').trim();
    const start = asNumber(entry.start, null, `captions[${index}].start`);
    const end = asNumber(entry.end, null, `captions[${index}].end`);

    if (!text) throw new Error(`captions[${index}].text cannot be empty.`);
    if (start === null || end === null || start < 0 || end <= start) {
      throw new Error(`captions[${index}] must have start >= 0 and end > start.`);
    }
    if (oneWordAtATime && text.split(/\s+/).length !== 1) {
      throw new Error(`captions[${index}] must contain exactly one word: "${text}".`);
    }

    return { text, start, end };
  }).sort((a, b) => a.start - b.start);

  for (let i = 1; i < normalized.length; i += 1) {
    if (normalized[i].start < normalized[i - 1].end) {
      throw new Error(`Caption timings overlap between "${normalized[i - 1].text}" and "${normalized[i].text}".`);
    }
  }

  return normalized;
}

function makeDrawTextFilter(caption, style, fontFile) {
  const fontSize = asNumber(style.fontSize, 150, 'style.fontSize');
  const y = style.y ?? 720;
  const outlineWidth = asNumber(style.outlineWidth, 8, 'style.outlineWidth');
  const shadowX = asNumber(style.shadowX, 6, 'style.shadowX');
  const shadowY = asNumber(style.shadowY, 6, 'style.shadowY');
  const color = ffmpegColor(style.color, '#C83803');
  const outlineColor = ffmpegColor(style.outlineColor, '#000000');
  const shadowColor = String(style.shadowColor || 'black@0.85');

  return [
    `drawtext=fontfile='${escapeFilterPath(fontFile)}'`,
    `text='${escapeFilterText(caption.text.toUpperCase())}'`,
    'x=(w-text_w)/2',
    `y=${y}`,
    `fontsize=${fontSize}`,
    `fontcolor=${color}`,
    `borderw=${outlineWidth}`,
    `bordercolor=${outlineColor}`,
    `shadowx=${shadowX}`,
    `shadowy=${shadowY}`,
    `shadowcolor=${shadowColor}`,
    `enable='between(t,${caption.start},${caption.end})'`
  ].join(':');
}

function run(command, args) {
  return new Promise((resolve, reject) => {
    const child = spawn(command, args, { stdio: 'inherit' });
    child.on('error', reject);
    child.on('close', code => {
      if (code === 0) resolve();
      else reject(new Error(`${command} exited with code ${code}.`));
    });
  });
}

async function main() {
  const args = parseArgs(process.argv.slice(2));
  if (args.help || !args.input || !args.captions || !args.output) {
    console.log(usage());
    if (!args.help) process.exitCode = 1;
    return;
  }

  if (!ffmpeg) throw new Error('ffmpeg-static did not provide an FFmpeg binary.');

  const input = path.resolve(ROOT, String(args.input));
  const captionFile = path.resolve(ROOT, String(args.captions));
  const output = path.resolve(ROOT, String(args.output));

  await fs.access(input);
  const config = JSON.parse(await fs.readFile(captionFile, 'utf8'));
  const style = config.style || {};
  const oneWordAtATime = config.oneWordAtATime !== false;
  const captions = validateCaptions(config.captions, oneWordAtATime);
  const fontFile = await resolveFont(args.font, style.fontFile);
  const fps = asNumber(style.fps, 30, 'style.fps');

  const filters = [
    `fps=${fps}`,
    ...captions.map(caption => makeDrawTextFilter(caption, style, fontFile))
  ].join(',');

  await fs.mkdir(path.dirname(output), { recursive: true });

  const ffmpegArgs = ['-y'];
  if (args['clip-start'] !== undefined) {
    ffmpegArgs.push('-ss', String(asNumber(args['clip-start'], 0, '--clip-start')));
  }
  ffmpegArgs.push('-i', input);
  if (args['clip-duration'] !== undefined) {
    ffmpegArgs.push('-t', String(asNumber(args['clip-duration'], 0, '--clip-duration')));
  }

  ffmpegArgs.push(
    '-vf', filters,
    '-map', '0:v:0',
    '-map', '0:a?',
    '-c:v', 'libx264',
    '-preset', String(style.preset || 'veryfast'),
    '-crf', String(asNumber(style.crf, 18, 'style.crf')),
    '-pix_fmt', 'yuv420p',
    '-c:a', 'aac',
    '-b:a', String(style.audioBitrate || '192k'),
    '-movflags', '+faststart',
    output
  );

  console.log(`Caption font: ${fontFile}`);
  console.log(`Caption color: ${style.color || '#C83803'}`);
  console.log(`Rendering ${captions.length} one-word captions to ${output}`);
  await run(ffmpeg, ffmpegArgs);
  console.log(`Created ${output}`);
}

main().catch(error => {
  console.error(error);
  process.exit(1);
});
