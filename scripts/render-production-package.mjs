import fs from 'node:fs/promises';
import path from 'node:path';
import { spawn } from 'node:child_process';
import sharp from 'sharp';
import ffmpeg from 'ffmpeg-static';
import QRCode from 'qrcode';

const ROOT = process.cwd();
const OUT = path.join(ROOT, 'dist-assets', 'production');
const QR_URL = 'https://epiccontentcreatorgrants.org/';
const LOGO_BASE64 = path.join(ROOT, 'renderer', 'assets', 'epic-logo-for-qr.base64.txt');
const EPISODE_FILTER = process.env.EPISODE_FILTER || '024';
const ZERO_HOLD_SECONDS = Number(process.env.COUNTDOWN_ZERO_HOLD_SECONDS || 1);

const C = {
  navy: '#031226', navy2: '#061a34', black: '#020812', orange: '#f15a24',
  white: '#f7f4ee', muted: '#bec8d4', skyline: '#07111f'
};

function esc(value = '') {
  return String(value).replace(/[&<>"']/g, ch => ({ '&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;', "'":'&#039;' }[ch]));
}

function wrap(text, max) {
  const words = String(text).split(/\s+/).filter(Boolean);
  const lines = [];
  let line = '';
  for (const word of words) {
    const next = line ? `${line} ${word}` : word;
    if (next.length > max && line) { lines.push(line); line = word; } else line = next;
  }
  if (line) lines.push(line);
  return lines.slice(0, 4);
}

function productionName(item) {
  if (item.project === 'fgbars') return `FGBars Episode ${item.episodeNumber} Production Screen`;
  if (item.project === 'epic') return `EPIC Episode ${item.episodeNumber} Production Screen`;
  return `FGB Episode ${item.episodeNumber} Production Screen`;
}

function projectLabel(item) {
  if (item.project === 'fgbars') return "Football's Greatest Bars";
  if (item.project === 'epic') return 'EPIC Communities';
  return "Football's Greatest Bears";
}

function brand(item) {
  if (item.project === 'fgbars') return 'FGBars';
  if (item.project === 'epic') return 'EPIC';
  return 'FGB';
}

async function makeQrDataUri(outputFile) {
  const qrBuffer = await QRCode.toBuffer(QR_URL, {
    errorCorrectionLevel: 'H',
    margin: 4,
    width: 1024,
    color: { dark: '#000000', light: '#ffffff' }
  });

  const logoBase64 = (await fs.readFile(LOGO_BASE64, 'utf8')).trim();
  const logoSource = Buffer.from(logoBase64, 'base64');
  const logoBuffer = await sharp(logoSource)
    .resize(96, 96, { fit: 'contain', background: { r: 255, g: 255, b: 255, alpha: 0 } })
    .extend({ top: 10, bottom: 10, left: 10, right: 10, background: { r: 255, g: 255, b: 255, alpha: 1 } })
    .png()
    .toBuffer();

  const brandedQr = await sharp(qrBuffer)
    .composite([{ input: logoBuffer, gravity: 'center' }])
    .png()
    .toBuffer();

  await fs.writeFile(outputFile, brandedQr);
  return `data:image/png;base64,${brandedQr.toString('base64')}`;
}

function skyline(width, y) {
  const xs = [65,140,230,325,440,535,650,755,860,1005,1120,1265,1390,1510,1625,1740];
  return xs.map((x, i) => {
    const h = 95 + (i % 4) * 35;
    return `<rect x="${x}" y="${y - h}" width="82" height="${h}" fill="${C.skyline}" opacity=".88"/>`;
  }).join('\n') + `<rect x="0" y="${y}" width="${width}" height="80" fill="${C.skyline}" opacity=".95"/>`;
}

function titleLines(lines, x, y, size) {
  return lines.map((line, i) => `<text x="${x}" y="${y + i * size * 1.08}" text-anchor="middle" fill="${C.orange}" font-family="Impact, Arial Narrow, Arial, sans-serif" font-size="${size}" font-weight="900" letter-spacing="1.5" style="paint-order:stroke;stroke:#000;stroke-width:${Math.max(4, size / 15)};stroke-linejoin:round">${esc(line).toUpperCase()}</text>`).join('\n');
}

function qrBlock(qrData, centerX, topY, size) {
  const x = centerX - size / 2;
  return `<text x="${centerX}" y="${topY - 28}" text-anchor="middle" fill="${C.white}" font-family="Impact, Arial Narrow, Arial, sans-serif" font-size="30" letter-spacing="4" style="paint-order:stroke;stroke:#000;stroke-width:4">SCAN TO LEARN MORE</text>
    <rect x="${x - 14}" y="${topY - 14}" width="${size + 28}" height="${size + 28}" rx="8" fill="#ffffff" stroke="${C.orange}" stroke-width="6"/>
    <image href="${qrData}" x="${x}" y="${topY}" width="${size}" height="${size}" preserveAspectRatio="xMidYMid meet" style="image-rendering:pixelated"/>
    <text x="${centerX}" y="${topY + size + 32}" text-anchor="middle" fill="${C.white}" font-family="Arial" font-size="22" font-weight="700" style="paint-order:stroke;stroke:#000;stroke-width:3">epiccontentcreatorgrants.org</text>`;
}

function productionSvg(item, qrData, includeTimer = true) {
  const w = 1920, h = 1080;
  const titleLinesWrapped = wrap(item.episodeTitle, 34);
  return `<svg xmlns="http://www.w3.org/2000/svg" width="${w}" height="${h}" viewBox="0 0 ${w} ${h}">
    <defs><radialGradient id="bg" cx="50%" cy="42%" r="72%"><stop offset="0%" stop-color="${C.navy2}"/><stop offset="58%" stop-color="${C.navy}"/><stop offset="100%" stop-color="${C.black}"/></radialGradient></defs>
    <rect width="${w}" height="${h}" fill="url(#bg)"/>
    <path d="M0 180 L260 0 L390 0 L0 610 Z" fill="#371005" opacity=".9"/>
    <path d="M1920 130 L1690 0 L1540 0 L1920 540 Z" fill="#2d0c06" opacity=".82"/>
    ${skyline(w, 1008)}
    <rect x="26" y="26" width="1868" height="1028" fill="none" stroke="${C.orange}" stroke-width="5"/>
    <rect x="0" y="0" width="${w}" height="18" fill="${C.orange}"/><rect x="0" y="1062" width="${w}" height="18" fill="${C.orange}"/>
    <text x="960" y="135" text-anchor="middle" fill="${C.white}" font-family="Rockwell, Georgia, serif" font-size="68" font-weight="900" letter-spacing="9" style="paint-order:stroke;stroke:#000;stroke-width:7;stroke-linejoin:round">${esc(projectLabel(item)).toUpperCase()}</text>
    <text x="960" y="216" text-anchor="middle" fill="${C.muted}" font-family="Impact, Arial Narrow, Arial, sans-serif" font-size="30" letter-spacing="7" style="paint-order:stroke;stroke:#000;stroke-width:3;stroke-linejoin:round">EPISODE ${esc(item.episodeNumber)}</text>
    ${titleLines(titleLinesWrapped, 960, 292, titleLinesWrapped.length > 2 ? 48 : 58)}
    ${includeTimer ? `<text x="960" y="650" text-anchor="middle" fill="${C.white}" font-family="Rockwell, Georgia, serif" font-size="190" font-weight="900" letter-spacing="16" style="paint-order:stroke;stroke:#081020;stroke-width:9;stroke-linejoin:round">15:00</text>` : ''}
    ${qrBlock(qrData, 1548, 714, 292)}
    <text x="1774" y="1025" fill="${C.orange}" font-family="Impact, Arial Narrow, Arial, sans-serif" font-size="34" letter-spacing="5" style="paint-order:stroke;stroke:#000;stroke-width:3">${esc(brand(item))}</text>
  </svg>`;
}

function thumbnailSvg(item) {
  const w = 1280, h = 720;
  const lines = wrap(item.episodeTitle.replace('|', ' '), 18);
  return `<svg xmlns="http://www.w3.org/2000/svg" width="${w}" height="${h}" viewBox="0 0 ${w} ${h}">
    <defs><radialGradient id="thumbBg" cx="48%" cy="42%" r="80%"><stop offset="0%" stop-color="#0b2749"/><stop offset="65%" stop-color="${C.navy}"/><stop offset="100%" stop-color="${C.black}"/></radialGradient></defs>
    <rect width="${w}" height="${h}" fill="url(#thumbBg)"/>
    <path d="M0 85 L220 0 L360 0 L0 470 Z" fill="#3f1205" opacity=".95"/>
    <rect x="18" y="18" width="1244" height="684" fill="none" stroke="${C.orange}" stroke-width="5"/>
    <text x="140" y="112" text-anchor="middle" fill="${C.white}" font-family="Rockwell, Georgia, serif" font-size="74" font-weight="900" style="paint-order:stroke;stroke:#000;stroke-width:5">FGB</text>
    <rect x="970" y="48" width="230" height="72" rx="8" fill="${C.orange}"/><text x="1085" y="95" text-anchor="middle" fill="#fff" font-family="Impact, Arial Narrow, Arial, sans-serif" font-size="38" letter-spacing="2" style="paint-order:stroke;stroke:#000;stroke-width:2">EP ${Number(item.episodeNumber)}</text>
    <text x="640" y="180" text-anchor="middle" fill="${C.white}" font-family="Rockwell, Georgia, serif" font-size="44" font-weight="900" letter-spacing="6" style="paint-order:stroke;stroke:#000;stroke-width:5;stroke-linejoin:round">${esc(projectLabel(item)).toUpperCase()}</text>
    ${titleLines(lines, 640, 300, lines.length > 2 ? 62 : 74)}
    <rect x="375" y="610" width="530" height="60" fill="${C.orange}"/><text x="640" y="654" text-anchor="middle" fill="#020812" font-family="Impact, Arial Narrow, Arial, sans-serif" font-size="42" font-weight="900">EPISODE ${Number(item.episodeNumber)}</text>
    <text x="640" y="700" text-anchor="middle" fill="${C.white}" font-family="Impact, Arial Narrow, Arial, sans-serif" font-size="28" letter-spacing="4" style="paint-order:stroke;stroke:#000;stroke-width:3">FOOTBALL'S GREATEST BEARS</text>
  </svg>`;
}

async function writePng(svg, file, width, height) {
  await sharp(Buffer.from(svg)).resize(width, height).png().toFile(file);
}

function run(cmd, args) {
  return new Promise((resolve, reject) => {
    const p = spawn(cmd, args, { stdio: 'inherit' });
    p.on('close', code => code === 0 ? resolve() : reject(new Error(`${cmd} exited ${code}`)));
  });
}

async function writeCountdownMp4(baseFile, outputFile, seconds) {
  const holdSeconds = ZERO_HOLD_SECONDS;
  const totalSeconds = seconds + holdSeconds;
  const fontFile = '/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf';
  const text = `%{eif\\:floor(max(0,${seconds}-t)/60)\\:d\\:2}\\:%{eif\\:mod(max(0,${seconds}-t),60)\\:d\\:2}`;
  const filter = `drawtext=fontfile=${fontFile}:text='${text}':x=(w-text_w)/2:y=515:fontsize=190:fontcolor=0xF7F4EE:borderw=9:bordercolor=0x081020:shadowx=5:shadowy=5:shadowcolor=black`;
  await run(ffmpeg, [
    '-y', '-loop', '1', '-framerate', '1', '-i', baseFile,
    '-f', 'lavfi', '-i', 'anullsrc=channel_layout=stereo:sample_rate=48000',
    '-t', String(totalSeconds), '-vf', filter,
    '-c:v', 'libx264', '-preset', 'ultrafast', '-tune', 'stillimage', '-crf', '18',
    '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-b:a', '128k', '-shortest', '-movflags', '+faststart',
    outputFile
  ]);
}

async function main() {
  const list = JSON.parse(await fs.readFile(path.join(ROOT, 'render-list.json'), 'utf8'));
  const item = list.find(entry => entry.episodeNumber === EPISODE_FILTER && entry.status !== 'title-pending');
  if (!item) throw new Error(`No ready render-list item found for episode ${EPISODE_FILTER}`);

  const name = productionName(item);
  const dir = path.join(OUT, name);
  await fs.rm(dir, { recursive: true, force: true });
  await fs.mkdir(dir, { recursive: true });

  const qrFile = path.join(dir, 'EPIC Functional QR With Logo.png');
  const qrData = await makeQrDataUri(qrFile);
  const productionScreen = path.join(dir, `${name}.png`);
  const countdownBase = path.join(dir, `${name} Countdown Base.png`);
  const thumbnail = path.join(dir, `${name} Thumbnail.png`);
  const video = path.join(dir, `${name}.mp4`);

  await writePng(productionSvg(item, qrData, true), productionScreen, 1920, 1080);
  await writePng(productionSvg(item, qrData, false), countdownBase, 1920, 1080);
  await writePng(thumbnailSvg(item), thumbnail, 1280, 720);
  await writeCountdownMp4(countdownBase, video, item.durationSeconds || 900);

  const manifest = {
    episode: name,
    title: item.episodeTitle,
    qr_target: QR_URL,
    countdown_start: '15:00',
    countdown_end: '00:00',
    zero_hold_seconds: ZERO_HOLD_SECONDS,
    expected_video_duration_seconds: (item.durationSeconds || 900) + ZERO_HOLD_SECONDS,
    status_progress_bar: 'disabled',
    files: [
      path.basename(productionScreen),
      path.basename(countdownBase),
      path.basename(thumbnail),
      path.basename(video),
      path.basename(qrFile)
    ]
  };
  await fs.writeFile(path.join(dir, 'manifest.json'), JSON.stringify(manifest, null, 2));
  console.log(`Rendered ${name} to ${dir}`);
}

main().catch(error => {
  console.error(error);
  process.exit(1);
});
