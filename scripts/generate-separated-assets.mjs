import fs from 'node:fs/promises';
import path from 'node:path';
import { spawn } from 'node:child_process';
import sharp from 'sharp';
import ffmpeg from 'ffmpeg-static';
import QRCode from 'qrcode';

const ROOT = process.cwd();
const OUT = path.join(ROOT, 'dist-assets');
const EPISODES = path.join(OUT, 'episodes');
const QR_URL = 'https://epiccontentcreatorgrants.org/';

const C = {
  navy: '#031226', navy2: '#061a34', black: '#020812', orange: '#f15a24',
  white: '#f7f4ee', muted: '#bec8d4'
};

function esc(v = '') {
  return String(v).replace(/[&<>"']/g, ch => ({ '&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;', "'":'&#039;' }[ch]));
}

function slug(v = '') {
  return String(v).toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '').slice(0, 80) || 'asset';
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

async function makeQrDataUri() {
  return QRCode.toDataURL(QR_URL, {
    errorCorrectionLevel: 'H',
    margin: 2,
    width: 512,
    color: { dark: '#000000', light: '#ffffff' }
  });
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

function productionName(item) {
  if (item.project === 'fgb') return `FGB Episode ${item.episodeNumber} Production Screen`;
  if (item.project === 'fgbars') return `FGBars Episode ${item.episodeNumber} Production Screen`;
  return `EPIC Episode ${item.episodeNumber} Production Screen`;
}

function skyline(w, y) {
  return [70,150,250,340,470,560,680,790,880,1020,1120,1270,1390,1510,1620,1760]
    .map((x, i) => `<rect x="${x}" y="${y - (80 + (i % 4) * 30)}" width="80" height="${80 + (i % 4) * 30}" fill="#07111f" opacity=".72"/>`).join('') +
    `<rect x="0" y="${y}" width="${w}" height="80" fill="#07111f" opacity=".85"/>`;
}

function titleLines(lines, x, y, size) {
  return lines.map((line, i) => `<text x="${x}" y="${y + i * size * 1.05}" text-anchor="middle" fill="${C.orange}" font-family="Impact, Arial Narrow, sans-serif" font-size="${size}" font-weight="900" letter-spacing="1.5" style="paint-order:stroke;stroke:#000;stroke-width:${Math.max(4, size / 15)};stroke-linejoin:round">${esc(line).toUpperCase()}</text>`).join('\n');
}

function qrBlock(qrData, centerX, topY, size) {
  const x = centerX - size / 2;
  return `<text x="${centerX}" y="${topY - 24}" text-anchor="middle" fill="${C.white}" font-family="Impact, Arial Narrow, sans-serif" font-size="24" letter-spacing="4" style="paint-order:stroke;stroke:#000;stroke-width:3">LEARN MORE</text>
    <rect x="${x - 6}" y="${topY - 6}" width="${size + 12}" height="${size + 12}" rx="18" fill="none" stroke="${C.orange}" stroke-width="4"/>
    <rect x="${x}" y="${topY}" width="${size}" height="${size}" rx="12" fill="#fff"/>
    <image href="${qrData}" x="${x}" y="${topY}" width="${size}" height="${size}" preserveAspectRatio="xMidYMid meet"/>
    <text x="${centerX}" y="${topY + size + 26}" text-anchor="middle" fill="${C.orange}" font-family="Arial" font-size="17">epiccontentcreatorgrants.org</text>`;
}

function backgroundSvg(item, qrData, includeTimer = true) {
  const w = 1920, h = 1080;
  const bars = item.project === 'fgbars';
  const lines = wrap(item.episodeTitle, 34);
  return `<svg xmlns="http://www.w3.org/2000/svg" width="${w}" height="${h}" viewBox="0 0 ${w} ${h}">
    <defs><radialGradient id="bg" cx="50%" cy="45%" r="70%"><stop offset="0%" stop-color="${bars ? '#4a2510' : C.navy2}"/><stop offset="60%" stop-color="${bars ? '#180a04' : C.navy}"/><stop offset="100%" stop-color="${C.black}"/></radialGradient></defs>
    <rect width="${w}" height="${h}" fill="url(#bg)"/>${bars ? '<rect y="778" width="1920" height="302" fill="#120805" opacity=".8"/>' : skyline(w, 1008)}
    <rect x="26" y="26" width="1868" height="1028" fill="none" stroke="${C.orange}" stroke-width="5"/>
    <rect x="0" y="0" width="${w}" height="18" fill="${C.orange}"/><rect x="0" y="1062" width="${w}" height="18" fill="${C.orange}"/>
    <text x="960" y="135" text-anchor="middle" fill="${C.white}" font-family="Rockwell, Georgia, serif" font-size="68" font-weight="900" letter-spacing="9" style="paint-order:stroke;stroke:#000;stroke-width:7;stroke-linejoin:round">${esc(projectLabel(item)).toUpperCase()}</text>
    <text x="960" y="216" text-anchor="middle" fill="${C.muted}" font-family="Impact, Arial Narrow, sans-serif" font-size="24" letter-spacing="7" style="paint-order:stroke;stroke:#000;stroke-width:3;stroke-linejoin:round">EPISODE ${esc(item.episodeNumber)}</text>
    ${titleLines(lines, 960, 292, lines.length > 2 ? 48 : 58)}
    ${includeTimer ? `<text x="960" y="650" text-anchor="middle" fill="${C.white}" font-family="Rockwell, Georgia, serif" font-size="190" font-weight="900" letter-spacing="16" style="paint-order:stroke;stroke:#081020;stroke-width:9;stroke-linejoin:round">15:00</text>` : ''}
    ${qrBlock(qrData, 1595, 810, 170)}
    <text x="1774" y="1025" fill="${C.orange}" font-family="Impact, Arial Narrow, sans-serif" font-size="34" letter-spacing="5" style="paint-order:stroke;stroke:#000;stroke-width:3">${esc(brand(item))}</text>
  </svg>`;
}

function thumbnailSvg(item) {
  const w = 1280, h = 720;
  const bars = item.project === 'fgbars';
  const lines = wrap(item.episodeTitle, bars ? 20 : 18);
  return `<svg xmlns="http://www.w3.org/2000/svg" width="${w}" height="${h}" viewBox="0 0 ${w} ${h}">
    <defs><radialGradient id="bg" cx="50%" cy="45%" r="75%"><stop offset="0%" stop-color="${bars ? '#5b2d12' : '#0b2749'}"/><stop offset="65%" stop-color="${bars ? '#1b0c05' : C.navy}"/><stop offset="100%" stop-color="${C.black}"/></radialGradient></defs>
    <rect width="${w}" height="${h}" fill="url(#bg)"/>${bars ? '<rect y="518" width="1280" height="202" fill="#120805" opacity=".8"/>' : skyline(w, 665)}
    <rect x="18" y="18" width="1244" height="684" fill="none" stroke="${C.orange}" stroke-width="5"/>
    <text x="135" y="110" text-anchor="middle" fill="${C.orange}" font-family="Impact, Arial Narrow, sans-serif" font-size="54" letter-spacing="3" style="paint-order:stroke;stroke:#000;stroke-width:4">${esc(brand(item)).toUpperCase()}</text>
    <rect x="970" y="42" width="230" height="70" rx="10" fill="${C.orange}"/><text x="1085" y="88" text-anchor="middle" fill="#fff" font-family="Impact, Arial Narrow, sans-serif" font-size="34" letter-spacing="3" style="paint-order:stroke;stroke:#000;stroke-width:2">EP ${esc(item.episodeNumber)}</text>
    <text x="640" y="180" text-anchor="middle" fill="${C.white}" font-family="Rockwell, Georgia, serif" font-size="44" font-weight="900" letter-spacing="6" style="paint-order:stroke;stroke:#000;stroke-width:5;stroke-linejoin:round">${esc(projectLabel(item)).toUpperCase()}</text>
    ${titleLines(lines, 640, 300, lines.length > 2 ? 66 : 78)}
    <text x="640" y="670" text-anchor="middle" fill="${C.white}" font-family="Impact, Arial Narrow, sans-serif" font-size="34" letter-spacing="5" style="paint-order:stroke;stroke:#000;stroke-width:4">${bars ? 'FOOTBALL COMMUNITY • SPORTS BARS • GAME DAY' : 'BEARS TALK • FOOTBALL ANALYSIS • FGB'}</text>
  </svg>`;
}

async function writePng(svg, file, w, h) {
  await sharp(Buffer.from(svg)).resize(w, h).png().toFile(file);
}

function run(cmd, args) {
  return new Promise((resolve, reject) => {
    const p = spawn(cmd, args, { stdio: 'inherit' });
    p.on('close', code => code === 0 ? resolve() : reject(new Error(`${cmd} exited ${code}`)));
  });
}

async function writeMp4(countdownBase, file, seconds) {
  const fontFile = '/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf';
  const text = `%{eif\\:floor(max(0,${seconds}-t)/60)\\:d\\:2}\\:%{eif\\:mod(max(0,${seconds}-t),60)\\:d\\:2}`;
  const filter = `drawtext=fontfile=${fontFile}:text='${text}':x=(w-text_w)/2:y=500:fontsize=190:fontcolor=0xF7F4EE:borderw=9:bordercolor=0x081020:shadowx=5:shadowy=5:shadowcolor=black`;
  await run(ffmpeg, ['-y','-loop','1','-framerate','1','-i',countdownBase,'-f','lavfi','-i','anullsrc=channel_layout=stereo:sample_rate=48000','-t',String(seconds),'-vf',filter,'-c:v','libx264','-preset','veryfast','-tune','stillimage','-pix_fmt','yuv420p','-c:a','aac','-b:a','128k','-shortest','-movflags','+faststart',file]);
}

async function main() {
  await fs.mkdir(EPISODES, { recursive: true });
  const list = JSON.parse(await fs.readFile(path.join(ROOT, 'render-list.json'), 'utf8'));
  const qrData = await makeQrDataUri();
  const manifest = [];
  for (const item of list) {
    if (item.status === 'title-pending') continue;
    const name = productionName(item);
    const id = `${name} - ${slug(item.episodeTitle)}`;
    const dir = path.join(EPISODES, id);
    await fs.mkdir(dir, { recursive: true });
    const bg = path.join(dir, `${name}.png`);
    const countdownBase = path.join(dir, `${name} Countdown Base.png`);
    const th = path.join(dir, `${name} Thumbnail.png`);
    const mp4 = path.join(dir, `${name}.mp4`);
    await writePng(backgroundSvg(item, qrData, true), bg, 1920, 1080);
    await writePng(backgroundSvg(item, qrData, false), countdownBase, 1920, 1080);
    await writePng(thumbnailSvg(item), th, 1280, 720);
    await writeMp4(countdownBase, mp4, item.durationSeconds || 900);
    manifest.push({ episode: name, item, files: { productionScreen: path.relative(OUT, bg), thumbnail: path.relative(OUT, th), video: path.relative(OUT, mp4) } });
  }
  await fs.writeFile(path.join(OUT, 'separate-manifest.json'), JSON.stringify(manifest, null, 2));
  console.log(`Generated ${manifest.length} separated countdown production screens.`);
}

main().catch(err => { console.error(err); process.exit(1); });
