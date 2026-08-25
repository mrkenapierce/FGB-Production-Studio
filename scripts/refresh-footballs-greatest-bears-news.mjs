import { createHash } from 'node:crypto';
import { readFile, writeFile } from 'node:fs/promises';
import assert from 'node:assert/strict';

const FEED_PATH = 'feeds/fgb-bears-news.xml';
const MAX_ITEMS = 8;
const MIN_ITEMS = 3;
const MAX_AGE_MS = 7 * 24 * 60 * 60 * 1000;
const USER_AGENT = 'FootballsGreatestBearsNews/1.0 (+https://www.youtube.com/@FootballsGreatestBears)';

const SOURCE_RULES = [
  { name: 'ChicagoBears.com', searchDomain: 'chicagobears.com', sourceUrl: 'https://www.chicagobears.com/', match: (host) => host === 'chicagobears.com' || host.endsWith('.chicagobears.com') },
  { name: 'ESPN', searchDomain: 'espn.com', sourceUrl: 'https://www.espn.com/nfl/team/_/name/chi/chicago-bears', match: (host) => host === 'espn.com' || host.endsWith('.espn.com') },
  { name: 'NFL.com', searchDomain: 'nfl.com', sourceUrl: 'https://www.nfl.com/teams/chicago-bears/', match: (host) => host === 'nfl.com' || host.endsWith('.nfl.com') },
  { name: 'NBC Sports Chicago', searchDomain: 'nbcsportschicago.com', sourceUrl: 'https://www.nbcsportschicago.com/', match: (host, path) => host === 'nbcsportschicago.com' || host.endsWith('.nbcsportschicago.com') || ((host === 'nbcsports.com' || host.endsWith('.nbcsports.com')) && path.startsWith('/chicago/')) },
  { name: 'CBS Sports', searchDomain: 'cbssports.com', sourceUrl: 'https://www.cbssports.com/nfl/teams/CHI/chicago-bears/', match: (host) => host === 'cbssports.com' || host.endsWith('.cbssports.com') },
  { name: 'Yahoo Sports', searchDomain: 'sports.yahoo.com', sourceUrl: 'https://sports.yahoo.com/nfl/teams/chicago/', match: (host) => host === 'yahoo.com' || host.endsWith('.yahoo.com') },
  { name: 'Pro Football Talk', searchDomain: 'nbcsports.com/nfl/profootballtalk', sourceUrl: 'https://www.nbcsports.com/nfl/profootballtalk', match: (host, path) => (host === 'nbcsports.com' || host.endsWith('.nbcsports.com')) && path.startsWith('/nfl/profootballtalk') },
  { name: 'The Athletic', searchDomain: 'nytimes.com/athletic', sourceUrl: 'https://www.nytimes.com/athletic/nfl/team/bears/', match: (host, path) => (host === 'nytimes.com' || host.endsWith('.nytimes.com')) && path.startsWith('/athletic/') },
  { name: 'Sports Illustrated', searchDomain: 'si.com/nfl/bears', sourceUrl: 'https://www.si.com/nfl/bears/', match: (host) => host === 'si.com' || host.endsWith('.si.com') },
];

const RSS_ENDPOINTS = [
  'https://www.chicagobears.com/rss/news',
  'https://www.nfl.com/feeds-rs/news/all-news.xml',
  'https://www.nbcsports.com/nfl/profootballtalk.rss',
  'https://www.nbcsportschicago.com/feed/',
  'https://www.cbssports.com/rss/headlines/nfl/',
  'https://sports.yahoo.com/nfl/rss.xml',
  'https://www.si.com/rss/si_nfl.rss',
];

function decodeXml(value = '') {
  return value
    .replace(/^<!\[CDATA\[|\]\]>$/g, '')
    .replace(/&amp;/g, '&')
    .replace(/&lt;/g, '<')
    .replace(/&gt;/g, '>')
    .replace(/&quot;/g, '"')
    .replace(/&#39;|&apos;/g, "'")
    .replace(/&#(\d+);/g, (_, code) => String.fromCodePoint(Number(code)))
    .replace(/&#x([0-9a-f]+);/gi, (_, code) => String.fromCodePoint(Number.parseInt(code, 16)))
    .trim();
}

function escapeXml(value = '') {
  return value.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&apos;');
}

function tag(block, name) {
  const match = block.match(new RegExp(`<${name}(?:\\s[^>]*)?>([\\s\\S]*?)<\\/${name}>`, 'i'));
  return match ? decodeXml(match[1]) : '';
}

function unwrapDiscoveryUrl(raw) {
  const decoded = decodeXml(raw);
  let url;
  try { url = new URL(decoded); } catch { return ''; }
  if (url.hostname === 'bing.com' || url.hostname.endsWith('.bing.com')) {
    const nested = url.searchParams.get('url') || url.searchParams.get('r');
    if (!nested) return '';
    try { url = new URL(decodeURIComponent(nested)); } catch { return ''; }
  }
  if (url.protocol !== 'https:' && url.protocol !== 'http:') return '';
  for (const key of [...url.searchParams.keys()]) {
    if (/^(utm_|ocid$|cmpid$|guccounter$|output$)/i.test(key)) url.searchParams.delete(key);
  }
  url.hash = '';
  return url.toString();
}

function classifySource(rawUrl) {
  let url;
  try { url = new URL(rawUrl); } catch { return null; }
  const host = url.hostname.toLowerCase().replace(/^www\./, '');
  const path = url.pathname.toLowerCase();
  return SOURCE_RULES.find((rule) => rule.match(host, path)) || null;
}

function cleanTitle(rawTitle) {
  return decodeXml(rawTitle)
    .replace(/<[^>]+>/g, ' ')
    .replace(/\s+-\s+(Chicago Bears|ESPN|NFL\.com|CBS Sports|Yahoo Sports|Sports Illustrated|The Athletic|NBC Sports.*)$/i, '')
    .replace(/\s+/g, ' ')
    .trim();
}

function isBearsStory(title) {
  return /\b(chicago bears|bears|halas hall)\b/i.test(title);
}

function parseRss(xml) {
  return [...xml.matchAll(/<item(?:\s[^>]*)?>([\s\S]*?)<\/item>/gi)].map((match) => ({
    title: cleanTitle(tag(match[1], 'title')),
    url: unwrapDiscoveryUrl(tag(match[1], 'link')),
    publishedAt: tag(match[1], 'pubDate') || tag(match[1], 'dc:date') || tag(match[1], 'published'),
  }));
}

async function fetchText(url) {
  const response = await fetch(url, { headers: { 'user-agent': USER_AGENT, accept: 'application/rss+xml, application/xml, text/xml, application/json;q=0.9, */*;q=0.1' }, signal: AbortSignal.timeout(20_000) });
  if (!response.ok) throw new Error(`${response.status} ${response.statusText} for ${url}`);
  return response.text();
}

async function fetchEspn() {
  const body = await fetchText('https://site.api.espn.com/apis/site/v2/sports/football/nfl/teams/chi/news');
  const data = JSON.parse(body);
  return (data.articles || []).map((article) => ({
    title: cleanTitle(article.headline || ''),
    url: article.links?.web?.href || article.links?.api?.news?.href || '',
    publishedAt: article.published || article.lastModified || '',
  }));
}

async function fetchBingFor(rule) {
  const query = encodeURIComponent(`"Chicago Bears" site:${rule.searchDomain}`);
  const url = `https://www.bing.com/news/search?q=${query}&format=rss&setlang=en-US&count=30&qft=interval%3d%227%22`;
  return parseRss(await fetchText(url));
}

function normalizeArticle(article, now) {
  const title = cleanTitle(article.title || '');
  const url = unwrapDiscoveryUrl(article.url || '');
  const source = classifySource(url);
  const publishedAt = new Date(article.publishedAt || '');
  if (!title || !url || !source || !isBearsStory(title) || Number.isNaN(publishedAt.valueOf())) return null;
  if (publishedAt > new Date(now.valueOf() + 60 * 60 * 1000) || now - publishedAt > MAX_AGE_MS) return null;
  return { title, url, source, publishedAt };
}

function selectArticles(candidates, now) {
  const unique = new Map();
  for (const candidate of candidates) {
    const article = normalizeArticle(candidate, now);
    if (!article) continue;
    const key = article.url.replace(/\/$/, '').toLowerCase();
    if (!unique.has(key)) unique.set(key, article);
  }
  const sorted = [...unique.values()].sort((a, b) => b.publishedAt - a.publishedAt);
  const selected = [];
  const perSource = new Map();
  for (const article of sorted) {
    const count = perSource.get(article.source.name) || 0;
    if (count >= 2) continue;
    selected.push(article);
    perSource.set(article.source.name, count + 1);
    if (selected.length === MAX_ITEMS) break;
  }
  return selected;
}

function itemSignature(items) {
  return items.map((item) => `${item.url}\n${item.title}`).join('\n---\n');
}

function renderFeed(items, now) {
  const renderedItems = items.map((item) => {
    const guid = createHash('sha256').update(item.url).digest('hex').slice(0, 20);
    const description = `Football's Greatest Bears news brief from ${item.source.name}: ${item.title}`;
    return `    <item>\n      <title>${escapeXml(item.title)}</title>\n      <description>${escapeXml(description)}</description>\n      <link>${escapeXml(item.url)}</link>\n      <guid isPermaLink="false">footballs-greatest-bears-news-${guid}</guid>\n      <pubDate>${item.publishedAt.toUTCString()}</pubDate>\n      <category>normal</category>\n      <source url="${escapeXml(item.source.sourceUrl)}">${escapeXml(item.source.name)}</source>\n    </item>`;
  }).join('\n\n');
  return `<?xml version="1.0" encoding="UTF-8"?>\n<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom">\n  <channel>\n    <title>Football&apos;s Greatest Bears News</title>\n    <link>https://www.youtube.com/@FootballsGreatestBears</link>\n    <description>Current Chicago Bears headlines from approved sources for Football&apos;s Greatest Bears live programming.</description>\n    <language>en-us</language>\n    <lastBuildDate>${now.toUTCString()}</lastBuildDate>\n    <ttl>5</ttl>\n    <atom:link href="https://raw.githubusercontent.com/mrkenapierce/FGB-Production-Studio/main/feeds/fgb-bears-news.xml" rel="self" type="application/rss+xml" />\n\n${renderedItems}\n  </channel>\n</rss>\n`;
}

function parseExistingSignature(xml) {
  return itemSignature(parseRss(xml).map((item) => ({ title: item.title, url: item.url })));
}

async function refresh() {
  const now = new Date();
  const jobs = [fetchEspn(), ...RSS_ENDPOINTS.map(async (url) => parseRss(await fetchText(url))), ...SOURCE_RULES.map(fetchBingFor)];
  const results = await Promise.allSettled(jobs);
  const candidates = results.flatMap((result) => result.status === 'fulfilled' ? result.value : []);
  const articles = selectArticles(candidates, now);
  if (articles.length < MIN_ITEMS) {
    const failures = results.filter((result) => result.status === 'rejected').length;
    throw new Error(`Safety stop: only ${articles.length} approved, fresh items found (${failures}/${results.length} sources failed); existing feed preserved.`);
  }
  const existing = await readFile(FEED_PATH, 'utf8');
  if (parseExistingSignature(existing) === itemSignature(articles)) {
    console.log(`No story changes; kept the existing ${articles.length}-item feed and timestamp.`);
    return;
  }
  await writeFile(FEED_PATH, renderFeed(articles, now), 'utf8');
  console.log(`Updated ${FEED_PATH} with ${articles.length} fresh, approved-source items.`);
}

function selfTest() {
  const rss = `<rss><channel><item><title><![CDATA[Bears test headline - ESPN]]></title><link>https://www.espn.com/nfl/story/_/id/1/bears-test?utm_source=x</link><pubDate>Tue, 25 Aug 2026 12:00:00 GMT</pubDate></item></channel></rss>`;
  const parsed = parseRss(rss);
  assert.equal(parsed.length, 1);
  assert.equal(parsed[0].title, 'Bears test headline');
  assert.equal(parsed[0].url, 'https://www.espn.com/nfl/story/_/id/1/bears-test');
  assert.equal(classifySource(parsed[0].url)?.name, 'ESPN');
  const selected = selectArticles(parsed, new Date('2026-08-25T13:00:00Z'));
  assert.equal(selected.length, 1);
  const output = renderFeed(selected, new Date('2026-08-25T13:00:00Z'));
  assert.match(output, /Football&apos;s Greatest Bears/);
  assert.match(output, /<source url="https:\/\/www\.espn\.com\/nfl\/team\/_\/name\/chi\/chicago-bears">ESPN<\/source>/);
  console.log('Self-test passed.');
}

if (process.argv.includes('--self-test')) selfTest();
else await refresh();
