import fs from 'node:fs/promises';
import path from 'node:path';
import { spawn } from 'node:child_process';
import sharp from 'sharp';
import ffmpeg from 'ffmpeg-static';

const ROOT = process.cwd();
const OUT = path.join(ROOT, 'dist-assets');
const EPISODES = path.join(OUT, 'episodes');

const C = {
  navy: '#031226', navy2: '#061a34', black: '#020812', orange: '#f15a24',
  white: '#f7f4ee', muted: '#bec8d4', brown: '#2b160c', gold: '#c68b3d'
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

async function loadQr() {
  try {
    const css = await fs.readFile(path.join(ROOT, 'renderer', 'styles.css'), 'utf8');
    const match = css.match(/data:image\/png;base64,([^'\")]+)/);
    if (match) return `data:image/png;base64,${match[1]}`;
  } catch {}
  return '';
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

function skyline(w, y) {
  return [70,150,250,340,470,560,680,790,880,1020,1120,1270,1390,1510,1620,1760]
    .map((x, i) => `<rect x="${x}" y="${y - (80 + (i % 4) * 30)}" width="80" height="${80 + (i % 4) * 30}" fill="#07111f" opacity=".72"/>`).join('') +
    `<rect x="0" y="${y}" width="${w}" height="80" fill="#07111f" opacity=".85"/>`;
}

function titleLines(lines, x, y, size) {
  return lines.map((line, i) => `<text x="${x}" y="${y + i * size * 1.05}" text-anchor="middle" fill="${C.orange}" font-family="Impact, Arial Narrow, sans-serif" font-size="${size}" font-weight="900" letter-spacing="1.5" style="paint-order:stroke;stroke:#000;stroke-width:${Math.max(4, size / 15)};stroke-linejoin:round">${esc(line).toUpperCase()}</text>`).join('\n');
}

function qr(qrData, x, y, size) {
  if (!qrData) return `<rect x="${x}" y="${y}" width="${size}" height="${size}" fill="#fff" stroke="${C.orange}" stroke-width="4"/><text x="${x + size/2}" y="${y + size/2}" text-anchor="middle" font-size="28">QR</text>`;
  return `<rect x="${x - 5}" y="${y - 5}" width="${size + 10}" height="${size + 10}" rx="18" fill="none" stroke="${C.orange}" stroke-width="4"/><rect x="${x}" y="${y}" width="${size}" height="${size}" rx="12" fill="#fff"/><image href="${qrData}" x="${x}" y="${y}" width="${size}" height="${size}" preserveAspectRatio="xMidYMid meet"/>`;
}

function backgroundSvg(item, qrData) {
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
    <text x="960" y="650" text-anchor="middle" fill="${C.white}" font-family="Rockwell, Georgia, serif" font-size="190" font-weight="900" letter-spacing="16" style="paint-order:stroke;stroke:#081020;stroke-width:9;stroke-linejoin:round">15:00</text>
    <text x="960" y="742" text-anchor="middle" fill="${C.white}" font-family="Impact, Arial Narrow, sans-serif" font-size="34" letter-spacing="7" style="paint-order:stroke;stroke:#000;stroke-width:4;stroke-linejoin:round">STARTING SOON</text>
    <rect x="480" y="805" width="960" height="18" rx="9" fill="#192d46"/><rect x="480" y="805" width="120" height="18" rx="9" fill="${C.orange}"/>
    <text x="1595" y="786" text-anchor="middle" fill="${C.white}" font-family="Impact, Arial Narrow, sans-serif" font-size="22" letter-spacing="4" style="paint-order:stroke;stroke:#000;stroke-width:3">LEARN MORE</text>
    ${qr(qrData, 1510, 810, 170)}
    <text x="1595" y="1006" text-anchor="middle" fill="${C.orange}" font-family="Arial" font-size="17">epiccontentcreatorgrants.org</text>
    <text x="1774" y="1025" fill="${C.orange}" font-family="Impact, Arial Narrow, sans-serif" font-size="34" letter-spacing="5" style="paint-order:stroke;stroke:#000;stroke-width:3">${esc(brand(item))}</text>
  </svg>`;
}

function thumbnailSvg(item, qrData) {
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

async function writeMp4(background, file, seconds) {
  await run(ffmpeg, ['-y','-loop','1','-i',background,'-t',String(seconds || 900),'-r','30','-c:v','libx264','-pix_fmt','yuv420p','-movflags','+faststart',file]);
}

async function main() {
  await fs.mkdir(EPISODES, { recursive: true });
  const list = JSON.parse(await fs.readFile(path.join(ROOT, 'render-list.json'), 'utf8'));
  const qrData = await loadQr();
  const manifest = [];
  for (const item of list) {
    if (item.status === 'title-pending') continue;
    const id = `${item.project}-${item.episodeNumber}-${slug(item.episodeTitle)}`;
    const dir = path.join(EPISODES, id);
    await fs.mkdir(dir, { recursive: true });
    const bg = path.join(dir, 'background.png');
    const th = path.join(dir, 'thumbnail.png');
    const mp4 = path.join(dir, 'starting-screen.mp4');
    await writePng(backgroundSvg(item, qrData), bg, 1920, 1080);
    await writePng(thumbnailSvg(item, qrData), th, 1280, 720);
    await writeMp4(bg, mp4, item.durationSeconds || 900);
    manifest.push({ episode: id, item, files: { background: path.relative(OUT, bg), thumbnail: path.relative(OUT, th), video: path.relative(OUT, mp4) } });
  }
  await fs.writeFile(path.join(OUT, 'separate-manifest.json'), JSON.stringify(manifest, null, 2));
  console.log(`Generated ${manifest.length} separated episode folders.`);
}

main().catch(err => { console.error(err); process.exit(1); });
