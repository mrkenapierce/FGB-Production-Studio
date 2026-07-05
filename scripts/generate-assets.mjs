import fs from 'node:fs/promises';
import path from 'node:path';
import sharp from 'sharp';

const ROOT = process.cwd();
const OUT = path.join(ROOT, 'dist-assets');
const BACKGROUNDS = path.join(OUT, 'backgrounds');
const THUMBNAILS = path.join(OUT, 'thumbnails');

const COLORS = {
  navy: '#031226',
  navy2: '#061a34',
  black: '#020812',
  orange: '#f15a24',
  white: '#f7f4ee',
  muted: '#bec8d4',
  barBrown: '#2b160c',
  barGold: '#c68b3d'
};

function esc(value = '') {
  return String(value).replace(/[&<>"']/g, ch => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#039;'
  }[ch]));
}

function slug(value = '') {
  return String(value).toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '').slice(0, 80) || 'asset';
}

function wrapText(text, maxChars) {
  const words = String(text).split(/\s+/).filter(Boolean);
  const lines = [];
  let line = '';
  for (const word of words) {
    const next = line ? `${line} ${word}` : word;
    if (next.length > maxChars && line) {
      lines.push(line);
      line = word;
    } else {
      line = next;
    }
  }
  if (line) lines.push(line);
  return lines.slice(0, 4);
}

async function loadQrDataUri() {
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

function brandLabel(item) {
  if (item.project === 'fgbars') return 'FGBars';
  if (item.project === 'epic') return 'EPIC';
  return 'FGB';
}

function episodeLabel(item) {
  if (item.project === 'fgbars') return `EPISODE ${esc(item.episodeNumber)}`;
  return `FGB EPISODE ${esc(item.episodeNumber)}`;
}

function qrBlock(qr, x, y, size = 180) {
  if (!qr) return `<rect x="${x}" y="${y}" width="${size}" height="${size}" rx="14" fill="#fff" stroke="${COLORS.orange}" stroke-width="4"/><text x="${x + size / 2}" y="${y + size / 2}" text-anchor="middle" fill="#111" font-size="20" font-family="Arial">QR</text>`;
  return `<rect x="${x - 5}" y="${y - 5}" width="${size + 10}" height="${size + 10}" rx="18" fill="none" stroke="${COLORS.orange}" stroke-width="4"/><rect x="${x}" y="${y}" width="${size}" height="${size}" rx="12" fill="#fff"/><image href="${qr}" x="${x}" y="${y}" width="${size}" height="${size}" preserveAspectRatio="xMidYMid meet"/>`;
}

function lineSpans(lines, x, y, size, color, family, weight = 900, spacing = 1.15) {
  return lines.map((line, idx) => `<text x="${x}" y="${y + idx * size * spacing}" text-anchor="middle" fill="${color}" font-size="${size}" font-family="${family}" font-weight="${weight}" letter-spacing="1.5" style="text-transform:uppercase;paint-order:stroke;stroke:#000;stroke-width:${Math.max(3, size / 18)};stroke-linejoin:round">${esc(line).toUpperCase()}</text>`).join('\n');
}

function skyline(width, y, color) {
  const buildings = [
    [70, 80], [150, 140], [250, 100], [340, 170], [470, 115], [560, 195], [680, 140], [790, 90], [880, 160], [1020, 120], [1120, 185], [1270, 105], [1390, 155], [1510, 90], [1620, 175], [1760, 120]
  ];
  return buildings.map(([x, h]) => `<rect x="${x}" y="${y - h}" width="80" height="${h}" fill="${color}" opacity="0.72"/>`).join('\n') + `<rect x="0" y="${y}" width="${width}" height="80" fill="${color}" opacity=".85"/>`;
}

function sportsBar(width, height) {
  return `
    <rect width="${width}" height="${height}" fill="${COLORS.barBrown}"/>
    <radialGradient id="barGlow" cx="50%" cy="34%" r="65%"><stop offset="0%" stop-color="#70401d"/><stop offset="55%" stop-color="#261208"/><stop offset="100%" stop-color="#090402"/></radialGradient>
    <rect width="${width}" height="${height}" fill="url(#barGlow)"/>
    <rect x="0" y="${height * 0.72}" width="${width}" height="${height * 0.28}" fill="#120805" opacity=".85"/>
    <circle cx="${width * 0.2}" cy="${height * 0.22}" r="52" fill="${COLORS.barGold}" opacity=".25"/>
    <circle cx="${width * 0.8}" cy="${height * 0.24}" r="52" fill="${COLORS.barGold}" opacity=".25"/>
    <rect x="${width * 0.12}" y="${height * 0.11}" width="190" height="100" rx="12" fill="#071323" stroke="#70401d" stroke-width="5" opacity=".88"/>
    <rect x="${width * 0.76}" y="${height * 0.11}" width="190" height="100" rx="12" fill="#071323" stroke="#70401d" stroke-width="5" opacity=".88"/>
  `;
}

function backgroundSvg(item, qr) {
  const isBars = item.project === 'fgbars';
  const w = 1920, h = 1080;
  const titleLines = wrapText(item.episodeTitle, 34);
  return `<svg xmlns="http://www.w3.org/2000/svg" width="${w}" height="${h}" viewBox="0 0 ${w} ${h}">
    <defs>
      <radialGradient id="bg" cx="50%" cy="45%" r="70%"><stop offset="0%" stop-color="${isBars ? '#42210f' : COLORS.navy2}"/><stop offset="60%" stop-color="${isBars ? '#170a04' : COLORS.navy}"/><stop offset="100%" stop-color="${COLORS.black}"/></radialGradient>
      <filter id="glow"><feGaussianBlur stdDeviation="5" result="blur"/><feMerge><feMergeNode in="blur"/><feMergeNode in="SourceGraphic"/></feMerge></filter>
    </defs>
    ${isBars ? sportsBar(w, h) : `<rect width="${w}" height="${h}" fill="url(#bg)"/>${skyline(w, 1008, '#07111f')}`}
    <rect x="26" y="26" width="1868" height="1028" fill="none" stroke="${COLORS.orange}" stroke-width="5" filter="url(#glow)"/>
    <rect x="0" y="0" width="${w}" height="18" fill="${COLORS.orange}"/><rect x="0" y="1062" width="${w}" height="18" fill="${COLORS.orange}"/>
    <text x="960" y="135" text-anchor="middle" fill="${COLORS.white}" font-family="Rockwell, Georgia, serif" font-size="68" font-weight="900" letter-spacing="9" style="paint-order:stroke;stroke:#000;stroke-width:7;stroke-linejoin:round">${esc(projectLabel(item)).toUpperCase()}</text>
    <text x="960" y="216" text-anchor="middle" fill="${COLORS.muted}" font-family="Impact, Arial Narrow, sans-serif" font-size="24" letter-spacing="7" style="paint-order:stroke;stroke:#000;stroke-width:3;stroke-linejoin:round">${episodeLabel(item)}</text>
    ${lineSpans(titleLines, 960, 292, titleLines.length > 2 ? 48 : 58, COLORS.orange, 'Impact, Arial Narrow, sans-serif')}
    <text x="960" y="650" text-anchor="middle" fill="${COLORS.white}" font-family="Rockwell, Georgia, serif" font-size="190" font-weight="900" letter-spacing="16" style="paint-order:stroke;stroke:#081020;stroke-width:9;stroke-linejoin:round">15:00</text>
    <text x="960" y="742" text-anchor="middle" fill="${COLORS.white}" font-family="Impact, Arial Narrow, sans-serif" font-size="34" letter-spacing="7" style="paint-order:stroke;stroke:#000;stroke-width:4;stroke-linejoin:round">STARTING SOON</text>
    <rect x="480" y="805" width="960" height="18" rx="9" fill="#192d46"/><rect x="480" y="805" width="120" height="18" rx="9" fill="${COLORS.orange}"/>
    <text x="1595" y="786" text-anchor="middle" fill="${COLORS.white}" font-family="Impact, Arial Narrow, sans-serif" font-size="22" letter-spacing="4" style="paint-order:stroke;stroke:#000;stroke-width:3">LEARN MORE</text>
    ${qrBlock(qr, 1510, 810, 170)}
    <text x="1595" y="1006" text-anchor="middle" fill="${COLORS.orange}" font-family="Arial" font-size="17">epiccontentcreatorgrants.org</text>
    <text x="1774" y="1025" fill="${COLORS.orange}" font-family="Impact, Arial Narrow, sans-serif" font-size="34" letter-spacing="5" style="paint-order:stroke;stroke:#000;stroke-width:3">${esc(brandLabel(item))}</text>
  </svg>`;
}

function thumbnailSvg(item, qr) {
  const isBars = item.project === 'fgbars';
  const w = 1280, h = 720;
  const titleLines = wrapText(item.episodeTitle, isBars ? 20 : 18);
  return `<svg xmlns="http://www.w3.org/2000/svg" width="${w}" height="${h}" viewBox="0 0 ${w} ${h}">
    <defs>
      <radialGradient id="thumbBg" cx="52%" cy="45%" r="75%"><stop offset="0%" stop-color="${isBars ? '#5b2d12' : '#0b2749'}"/><stop offset="65%" stop-color="${isBars ? '#1b0c05' : '#031226'}"/><stop offset="100%" stop-color="#020812"/></radialGradient>
      <filter id="soft"><feGaussianBlur stdDeviation="4" result="blur"/><feMerge><feMergeNode in="blur"/><feMergeNode in="SourceGraphic"/></feMerge></filter>
    </defs>
    ${isBars ? sportsBar(w, h) : `<rect width="${w}" height="${h}" fill="url(#thumbBg)"/>${skyline(w, 665, '#07111f')}`}
    <rect x="18" y="18" width="1244" height="684" fill="none" stroke="${COLORS.orange}" stroke-width="5" filter="url(#soft)"/>
    <path d="M100 98 L185 42 L270 98 L240 160 L130 160 Z" fill="${COLORS.black}" stroke="${COLORS.orange}" stroke-width="5"/>
    <text x="185" y="125" text-anchor="middle" fill="${COLORS.orange}" font-family="Impact, Arial Narrow, sans-serif" font-size="52" letter-spacing="3" style="paint-order:stroke;stroke:#000;stroke-width:4">${esc(brandLabel(item)).toUpperCase()}</text>
    <rect x="970" y="42" width="230" height="70" rx="10" fill="${COLORS.orange}"/>
    <text x="1085" y="88" text-anchor="middle" fill="#fff" font-family="Impact, Arial Narrow, sans-serif" font-size="34" letter-spacing="3" style="paint-order:stroke;stroke:#000;stroke-width:2">EP ${esc(item.episodeNumber)}</text>
    <text x="640" y="180" text-anchor="middle" fill="${COLORS.white}" font-family="Rockwell, Georgia, serif" font-size="44" font-weight="900" letter-spacing="6" style="paint-order:stroke;stroke:#000;stroke-width:5;stroke-linejoin:round">${esc(projectLabel(item)).toUpperCase()}</text>
    ${lineSpans(titleLines, 640, 300, titleLines.length > 2 ? 66 : 78, COLORS.orange, 'Impact, Arial Narrow, sans-serif', 900, 1.02)}
    <g opacity=".88"><path d="M62 590 C170 535, 310 535, 445 590" fill="none" stroke="${COLORS.orange}" stroke-width="10" stroke-linecap="round"/><path d="M835 590 C970 535, 1110 535, 1218 590" fill="none" stroke="${COLORS.orange}" stroke-width="10" stroke-linecap="round"/></g>
    <text x="640" y="670" text-anchor="middle" fill="${COLORS.white}" font-family="Impact, Arial Narrow, sans-serif" font-size="34" letter-spacing="5" style="paint-order:stroke;stroke:#000;stroke-width:4">${isBars ? 'FOOTBALL COMMUNITY • SPORTS BARS • GAME DAY' : 'BEARS TALK • FOOTBALL ANALYSIS • FGB'}</text>
  </svg>`;
}

async function writePng(svg, file, width, height) {
  await sharp(Buffer.from(svg)).resize(width, height).png().toFile(file);
}

async function main() {
  await fs.mkdir(BACKGROUNDS, { recursive: true });
  await fs.mkdir(THUMBNAILS, { recursive: true });
  const list = JSON.parse(await fs.readFile(path.join(ROOT, 'render-list.json'), 'utf8'));
  const qr = await loadQrDataUri();
  const manifest = [];
  for (const item of list) {
    const base = `${item.project}-${item.episodeNumber}-${slug(item.episodeTitle)}`;
    const bgFile = path.join(BACKGROUNDS, `${base}-background.png`);
    const thFile = path.join(THUMBNAILS, `${base}-thumbnail.png`);
    await writePng(backgroundSvg(item, qr), bgFile, 1920, 1080);
    await writePng(thumbnailSvg(item, qr), thFile, 1280, 720);
    manifest.push({ item, background: path.relative(OUT, bgFile), thumbnail: path.relative(OUT, thFile) });
  }
  await fs.writeFile(path.join(OUT, 'manifest.json'), JSON.stringify(manifest, null, 2));
  console.log(`Generated ${manifest.length} background screens and ${manifest.length} thumbnails.`);
}

main().catch(err => {
  console.error(err);
  process.exit(1);
});
