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
const EPISODE_FILTER = process.env.EPISODE_FILTER || '003';
const ZERO_HOLD_SECONDS = Number(process.env.COUNTDOWN_ZERO_HOLD_SECONDS || 1);

const C = {
  orange: '#f15a24', white: '#f7f4ee', muted: '#c4cad1',
  panel: '#061830', dark: '#020812', side: '#010812', skyline: '#05101f'
};

function esc(v = '') {
  return String(v).replace(/[&<>"']/g, ch => ({ '&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;', "'":'&#039;' }[ch]));
}

function productionName(item) {
  if (item.project === 'fgbars') return `FGBars Episode ${item.episodeNumber} Production Screen`;
  if (item.project === 'epic') return `EPIC Episode ${item.episodeNumber} Production Screen`;
  return `FGB Episode ${item.episodeNumber} Production Screen`;
}

function projectLabel(item) {
  if (item.project === 'fgbars') return "FOOTBALL'S GREATEST BARS";
  if (item.project === 'epic') return 'EPIC COMMUNITIES';
  return "FOOTBALL'S GREATEST BEARS";
}

function projectBrand(item) {
  if (item.project === 'fgbars') return 'FGBARS';
  if (item.project === 'epic') return 'EPIC';
  return 'FGB';
}

function gameNumber(item) {
  const n = Number(item.episodeNumber);
  return Number.isFinite(n) ? Math.max(1, n - 21) : 1;
}

function episodeSubtitle(item) {
  if (item.episodeSubtitle) return String(item.episodeSubtitle).toUpperCase();
  if (item.project === 'fgb') return `2026 BEARS SEASON PREDICTION SERIES - GAME ${gameNumber(item)} OF 17`;
  return '';
}

function wrapTitle(title) {
  const clean = String(title).replace(/\s*\|\s*.*/, '').trim();
  if (/Welcome to Football's Greatest Bars/i.test(clean)) return ["WELCOME TO FOOTBALL'S", 'GREATEST BARS'];
  if (/Are the Bears Better Than the Jets\?/i.test(clean)) return ['ARE THE BEARS BETTER THAN', 'THE JETS?'];
  if (/Can Caleb Williams Beat the Eagles/i.test(clean)) return ['CAN CALEB WILLIAMS BEAT THE', 'EAGLES? | EAGLES PREVIEW'];
  const words = clean.toUpperCase().split(/\s+/);
  const lines = [];
  let line = '';
  for (const word of words) {
    const next = line ? `${line} ${word}` : word;
    if (next.length > 29 && line) { lines.push(line); line = word; } else line = next;
  }
  if (line) lines.push(line);
  return lines.slice(0, 3);
}

async function makeQr(outputFile) {
  const qrBuffer = await QRCode.toBuffer(QR_URL, {
    errorCorrectionLevel: 'H', margin: 4, width: 1024,
    color: { dark: '#000000', light: '#ffffff' }
  });
  let logoSource = null;
  try { logoSource = Buffer.from((await fs.readFile(LOGO_BASE64, 'utf8')).trim(), 'base64'); } catch {}
  if (!logoSource) { await fs.writeFile(outputFile, qrBuffer); return `data:image/png;base64,${qrBuffer.toString('base64')}`; }
  const logo = await sharp(logoSource).resize(96, 96, { fit: 'contain', background: { r:255, g:255, b:255, alpha:0 } }).extend({ top:10, bottom:10, left:10, right:10, background: { r:255, g:255, b:255, alpha:1 } }).png().toBuffer();
  const out = await sharp(qrBuffer).composite([{ input: logo, gravity: 'center' }]).png().toBuffer();
  await fs.writeFile(outputFile, out);
  return `data:image/png;base64,${out.toString('base64')}`;
}

function skyline() {
  const items = [[0,70,85],[64,135,95],[140,230,125],[230,318,160],[325,410,230],[440,535,85],[535,640,120],[650,755,155],[755,840,210],[860,955,85],[980,1085,120],[1125,1230,160],[1260,1360,210],[1390,1495,210],[1525,1618,170],[1660,1770,220],[1815,1900,100]];
  return items.map(([x1,x2,h], index) => {
    const y = 1008 - h;
    const windows = [];
    const startX = x1 + 18;
    const startY = y + 25;
    for (let wy = startY; wy < 992; wy += 28) {
      for (let wx = startX; wx < x2 - 12; wx += 26) {
        if ((Math.floor(wx / 13) + Math.floor(wy / 14) + index) % 3 !== 0) {
          windows.push(`<rect x="${wx}" y="${wy}" width="6" height="7" fill="${C.orange}" opacity=".9"/>`);
        }
      }
    }
    return `<rect x="${x1}" y="${y}" width="${x2-x1}" height="${h}" fill="${C.skyline}"/>${windows.join('')}`;
  }).join('\n') + `<rect x="0" y="1008" width="1920" height="72" fill="${C.skyline}"/>`;
}

function titleSvg(lines) {
  const startY = lines.length === 1 ? 306 : 292;
  return lines.map((line, i) => `<text x="960" y="${startY + i * 78}" text-anchor="middle" fill="${C.orange}" font-family="Impact, Arial Narrow, Arial, sans-serif" font-size="62" font-weight="900" letter-spacing="1" style="paint-order:stroke;stroke:#000;stroke-width:5;stroke-linejoin:round">${esc(line)}</text>`).join('\n');
}

function qrBlock(qrData) {
  const qx = 1394, qy = 700, s = 320, cx = qx + s / 2;
  return `<text x="${cx}" y="${qy - 12}" text-anchor="middle" fill="${C.white}" font-family="Impact, Arial Narrow, Arial, sans-serif" font-size="30" font-weight="900" style="paint-order:stroke;stroke:#000;stroke-width:3">SCAN TO LEARN MORE</text>
  <rect x="${qx - 7}" y="${qy - 7}" width="${s + 14}" height="${s + 14}" fill="#fff" stroke="${C.orange}" stroke-width="5"/>
  <image href="${qrData}" x="${qx}" y="${qy}" width="${s}" height="${s}" preserveAspectRatio="xMidYMid meet" style="image-rendering:pixelated"/>
  <text x="${cx}" y="1056" text-anchor="middle" fill="${C.white}" font-family="Arial Narrow, Arial, sans-serif" font-size="22" font-weight="900" style="paint-order:stroke;stroke:#000;stroke-width:3">epiccontentcreatorgrants.org</text>`;
}

function productionSvg(item, qrData, includeTimer) {
  const lines = wrapTitle(item.episodeTitle);
  const subtitle = episodeSubtitle(item);
  return `<svg xmlns="http://www.w3.org/2000/svg" width="1920" height="1080" viewBox="0 0 1920 1080">
  <rect width="1920" height="1080" fill="${C.dark}"/>
  <rect x="360" y="20" width="1180" height="1040" fill="${C.panel}"/>
  <rect x="0" y="20" width="360" height="1040" fill="${C.side}"/><rect x="1540" y="20" width="380" height="1040" fill="${C.side}"/>
  <path d="M0 175 L225 20 L390 20 L0 610 Z" fill="#4c1407"/><path d="M1920 130 L1565 20 L1540 20 L1920 545 Z" fill="#4c1407"/>
  ${skyline()}
  <rect x="0" y="0" width="1920" height="19" fill="${C.orange}"/><rect x="0" y="1061" width="1920" height="19" fill="${C.orange}"/>
  <rect x="25" y="25" width="1870" height="1030" fill="none" stroke="${C.orange}" stroke-width="5"/>
  <text x="960" y="135" text-anchor="middle" fill="${C.white}" font-family="Georgia, serif" font-size="62" font-weight="900" letter-spacing="2" style="paint-order:stroke;stroke:#000;stroke-width:6;stroke-linejoin:round">${esc(projectLabel(item))}</text>
  <text x="960" y="215" text-anchor="middle" fill="${C.muted}" font-family="Impact, Arial Narrow, Arial, sans-serif" font-size="30" font-weight="900" style="paint-order:stroke;stroke:#000;stroke-width:3">EPISODE ${esc(item.episodeNumber)}</text>
  ${titleSvg(lines)}
  ${subtitle ? `<text x="960" y="455" text-anchor="middle" fill="${C.white}" font-family="Impact, Arial Narrow, Arial, sans-serif" font-size="29" font-weight="900" style="paint-order:stroke;stroke:#000;stroke-width:3">${esc(subtitle)}</text>` : ''}
  ${includeTimer ? `<text x="960" y="665" text-anchor="middle" fill="${C.white}" font-family="Georgia, serif" font-size="174" font-weight="900" style="paint-order:stroke;stroke:#000;stroke-width:8;stroke-linejoin:round">15:00</text>` : ''}
  ${qrBlock(qrData)}
  <text x="1850" y="1053" text-anchor="end" fill="${C.orange}" font-family="Impact, Arial Narrow, Arial, sans-serif" font-size="32" font-weight="900" style="paint-order:stroke;stroke:#000;stroke-width:3">${esc(projectBrand(item))}</text>
  </svg>`;
}

function thumbnailSvg(item) {
  const title = String(item.episodeTitle).replace(/\s*\|\s*.*/, '').toUpperCase();
  const lines = /ARE THE BEARS BETTER THAN THE JETS/.test(title) ? ['ARE THE BEARS', 'BETTER THAN', 'THE JETS?'] : wrapTitle(title);
  const brand = projectBrand(item);
  return `<svg xmlns="http://www.w3.org/2000/svg" width="1536" height="1024" viewBox="0 0 1536 1024">
  <rect width="1536" height="1024" fill="#03080f"/><path d="M0 140 L210 0 L360 0 L0 545 Z" fill="#691e04"/>
  <rect x="0" y="0" width="1536" height="1024" fill="none" stroke="${C.orange}" stroke-width="6"/>
  <text x="768" y="205" text-anchor="middle" fill="${C.white}" font-family="Impact, Arial Narrow, Arial, sans-serif" font-size="190" font-weight="900" style="paint-order:stroke;stroke:#000;stroke-width:8">${esc(brand)}</text>
  ${lines.map((line, i) => `<text x="768" y="${400 + i*95}" text-anchor="middle" fill="${i===0 ? C.orange : C.white}" font-family="Impact, Arial Narrow, Arial, sans-serif" font-size="86" font-weight="900" style="paint-order:stroke;stroke:#000;stroke-width:5">${esc(line)}</text>`).join('\n')}
  <rect x="405" y="745" width="725" height="125" fill="${C.orange}"/><text x="768" y="838" text-anchor="middle" fill="#080808" font-family="Impact, Arial Narrow, Arial, sans-serif" font-size="78" font-weight="900">EPISODE ${Number(item.episodeNumber)}</text>
  <text x="768" y="980" text-anchor="middle" fill="${C.white}" font-family="Impact, Arial Narrow, Arial, sans-serif" font-size="42" letter-spacing="10" style="paint-order:stroke;stroke:#000;stroke-width:3">${esc(projectLabel(item))}</text>
  </svg>`;
}

async function writePng(svg, file, w, h) {
  await sharp(Buffer.from(svg)).resize(w, h).png().toFile(file);
}

function run(cmd, args) {
  return new Promise((resolve, reject) => {
    const child = spawn(cmd, args, { stdio: 'inherit' });
    child.on('close', code => code === 0 ? resolve() : reject(new Error(`${cmd} exited ${code}`)));
  });
}

async function writeCountdown(baseFile, outputFile, seconds) {
  const total = seconds + ZERO_HOLD_SECONDS;
  const fontFile = '/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf';
  const text = `%{eif\\:floor(max(0\\,${seconds}-t)/60)\\:d\\:2}\\:%{eif\\:mod(max(0\\,${seconds}-t)\\,60)\\:d\\:2}`;
  const vf = `drawtext=fontfile='${fontFile}':text='${text}':x=(w-text_w)/2:y=515:fontsize=174:fontcolor=0xF7F4EE:borderw=8:bordercolor=0x000000:shadowx=4:shadowy=4:shadowcolor=black`;
  await run(ffmpeg, ['-y','-loop','1','-framerate','1','-i',baseFile,'-f','lavfi','-i','anullsrc=channel_layout=stereo:sample_rate=48000','-t',String(total),'-vf',vf,'-c:v','libx264','-preset','ultrafast','-tune','stillimage','-crf','18','-pix_fmt','yuv420p','-c:a','aac','-b:a','128k','-shortest','-movflags','+faststart',outputFile]);
}

async function main() {
  const list = JSON.parse(await fs.readFile(path.join(ROOT, 'render-list.json'), 'utf8'));
  const item = list.find(entry => entry.episodeNumber === EPISODE_FILTER && entry.status !== 'title-pending');
  if (!item) throw new Error(`No ready item found for episode ${EPISODE_FILTER}`);
  const name = productionName(item);
  const dir = path.join(OUT, name);
  await fs.rm(dir, { recursive: true, force: true });
  await fs.mkdir(dir, { recursive: true });
  const qrFile = path.join(dir, 'EPIC Functional QR With Logo.png');
  const qrData = await makeQr(qrFile);
  const screen = path.join(dir, `${name}.png`);
  const base = path.join(dir, `${name} Countdown Base.png`);
  const thumb = path.join(dir, `${name} Thumbnail.png`);
  const video = path.join(dir, `${name}.mp4`);
  await writePng(productionSvg(item, qrData, true), screen, 1920, 1080);
  await writePng(productionSvg(item, qrData, false), base, 1920, 1080);
  await writePng(thumbnailSvg(item), thumb, 1536, 1024);
  await writeCountdown(base, video, item.durationSeconds || 900);
  await fs.writeFile(path.join(dir, 'manifest.json'), JSON.stringify({
    episode: name,
    project: item.project,
    title: item.episodeTitle,
    subtitle: item.episodeSubtitle || null,
    production_screen_protocol: 'Use uploaded Episode 025 production screen layout; preserve design and coloration',
    countdown_start: '15:00',
    countdown_end: '00:00',
    zero_hold_seconds: ZERO_HOLD_SECONDS,
    expected_video_duration_seconds: (item.durationSeconds || 900) + ZERO_HOLD_SECONDS,
    qr_target: QR_URL,
    files: [path.basename(screen), path.basename(base), path.basename(video), path.basename(thumb), path.basename(qrFile)]
  }, null, 2));
  console.log(`Rendered ${name} using standardized production screen protocol.`);
}

main().catch(error => { console.error(error); process.exit(1); });
