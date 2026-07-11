import fs from 'node:fs/promises';
import path from 'node:path';
import { spawn } from 'node:child_process';
import ffmpeg from 'ffmpeg-static';

const ROOT = process.cwd();

function parseArgs(argv) {
  const args = {};
  for (let index = 0; index < argv.length; index += 1) {
    const token = argv[index];
    if (!token.startsWith('--')) continue;
    const key = token.slice(2);
    const value = argv[index + 1] && !argv[index + 1].startsWith('--') ? argv[++index] : true;
    args[key] = value;
  }
  return args;
}

function numberArg(value, fallback, label) {
  if (value === undefined || value === null || value === '') return fallback;
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) throw new Error(`${label} must be a valid number.`);
  return parsed;
}

function usage() {
  return [
    'Usage:',
    '  node scripts/add-background-music.mjs \\',
    '    --input <silent-video.mp4> \\',
    '    --music <licensed-track.mp3> \\',
    '    --license <license-record.json> \\',
    '    --output <youtube-final.mp4> \\',
    '    --duration 570',
    '',
    'Optional: --volume 0.15 --fade-in 2 --fade-out 5'
  ].join('\n');
}

function run(command, args) {
  return new Promise((resolve, reject) => {
    const child = spawn(command, args, { stdio: 'inherit' });
    child.on('error', reject);
    child.on('close', code => code === 0 ? resolve() : reject(new Error(`${command} exited with code ${code}.`)));
  });
}

function validateLicense(record) {
  const required = ['trackTitle', 'artist', 'source', 'licenseType', 'downloadDate'];
  if (String(record?.status || '').toLowerCase() !== 'approved') {
    throw new Error('Music license record status must be "approved".');
  }
  for (const field of required) {
    if (!String(record?.[field] || '').trim()) throw new Error(`Music license record is missing ${field}.`);
  }
  if (record.attributionRequired === true && !String(record.attributionText || '').trim()) {
    throw new Error('Attribution text is required for this track.');
  }
}

async function main() {
  const args = parseArgs(process.argv.slice(2));
  if (args.help || !args.input || !args.music || !args.license || !args.output || !args.duration) {
    console.log(usage());
    if (!args.help) process.exitCode = 1;
    return;
  }
  if (!ffmpeg) throw new Error('ffmpeg-static did not provide an FFmpeg binary.');

  const input = path.resolve(ROOT, String(args.input));
  const music = path.resolve(ROOT, String(args.music));
  const licenseFile = path.resolve(ROOT, String(args.license));
  const output = path.resolve(ROOT, String(args.output));
  const duration = numberArg(args.duration, 570, '--duration');
  const volume = numberArg(args.volume, 0.15, '--volume');
  const fadeIn = Math.max(0, numberArg(args['fade-in'], 2, '--fade-in'));
  const fadeOut = Math.max(0, numberArg(args['fade-out'], 5, '--fade-out'));
  const fadeOutStart = Math.max(0, duration - fadeOut);

  await Promise.all([fs.access(input), fs.access(music), fs.access(licenseFile)]);
  const license = JSON.parse(await fs.readFile(licenseFile, 'utf8'));
  validateLicense(license);
  await fs.mkdir(path.dirname(output), { recursive: true });

  const audioFilter = [
    `volume=${volume}`,
    `afade=t=in:st=0:d=${fadeIn}`,
    `afade=t=out:st=${fadeOutStart}:d=${fadeOut}`,
    `atrim=duration=${duration}`,
    'asetpts=N/SR/TB',
    'alimiter=limit=0.95'
  ].join(',');

  await run(ffmpeg, [
    '-y',
    '-i', input,
    '-stream_loop', '-1',
    '-i', music,
    '-filter_complex', `[1:a]${audioFilter}[music]`,
    '-map', '0:v:0',
    '-map', '[music]',
    '-t', String(duration),
    '-c:v', 'copy',
    '-c:a', 'aac',
    '-b:a', '192k',
    '-ar', '48000',
    '-movflags', '+faststart',
    '-metadata', `comment=Background music: ${license.trackTitle} by ${license.artist}`,
    output
  ]);

  const outputDirectory = path.dirname(output);
  const copiedLicense = path.join(outputDirectory, 'Background Music License Record.json');
  await fs.copyFile(licenseFile, copiedLicense);
  await fs.writeFile(path.join(outputDirectory, 'Background Music Mix Manifest.json'), JSON.stringify({
    video: path.basename(output),
    durationSeconds: duration,
    music: {
      trackTitle: license.trackTitle,
      artist: license.artist,
      source: license.source,
      licenseType: license.licenseType,
      attributionRequired: license.attributionRequired,
      attributionText: license.attributionText || null,
      volume,
      looped: true,
      fadeInSeconds: fadeIn,
      fadeOutSeconds: fadeOut
    },
    youtubeReady: {
      videoCodec: 'H.264 copied from source',
      audioCodec: 'AAC',
      audioBitrate: '192k',
      audioSampleRate: 48000,
      fastStart: true
    }
  }, null, 2));

  console.log(`Created ${output}`);
}

main().catch(error => {
  console.error(error);
  process.exit(1);
});