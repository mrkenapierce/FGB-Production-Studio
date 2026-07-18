import test from 'node:test';
import assert from 'node:assert/strict';
import {
  buildCandidateWindows,
  formatTimestamp,
  generateWordCaptions,
  parseTimestamp,
  parseTranscriptText,
  selectCandidates,
} from '../scripts/generate-produced-shorts.mjs';

const SAMPLE_SRT = `1
00:00:00,000 --> 00:00:05,000
What if the Bears offense is already better than most fans expect?

2
00:00:05,000 --> 00:00:11,000
The difference is not one player. It is how the entire system creates answers.

3
00:00:11,000 --> 00:00:18,000
Caleb Williams now has clearer reads, faster outlets, and a coach who understands spacing.

4
00:00:18,000 --> 00:00:25,000
That does not guarantee a championship, but it changes the weekly floor of the offense.

5
00:00:25,000 --> 00:00:32,000
And that is the part Bears fans should watch first this season.

6
00:00:40,000 --> 00:00:46,000
Nobody talks enough about the defense creating short fields.

7
00:00:46,000 --> 00:00:53,000
If the turnover rate rises, the offense does not need to be perfect every drive.

8
00:00:53,000 --> 00:01:01,000
That is how a good team becomes a playoff team over seventeen games.
`;

test('timestamp parsing and formatting are stable', () => {
  assert.equal(parseTimestamp('01:02.500'), 62.5);
  assert.equal(parseTimestamp('00:01:02,250'), 62.25);
  assert.equal(formatTimestamp(62.5, true), '01:02.500');
});

test('SRT parser returns ordered clean cues', () => {
  const cues = parseTranscriptText(SAMPLE_SRT);
  assert.equal(cues.length, 8);
  assert.equal(cues[0].start, 0);
  assert.equal(cues[0].end, 5);
  assert.match(cues[0].text, /What if the Bears offense/);
  assert.equal(cues.at(-1).end, 61);
});

test('VTT parser ignores headers and styling tags', () => {
  const cues = parseTranscriptText(`WEBVTT\n\n00:00.000 --> 00:03.000\n<c.green>Hello &amp; welcome</c>\n\n00:03.000 --> 00:07.000\nThis is a test.\n`);
  assert.deepEqual(cues, [
    { start: 0, end: 3, text: 'Hello & welcome' },
    { start: 3, end: 7, text: 'This is a test.' },
  ]);
});

test('candidate selection favors complete, non-overlapping ideas', () => {
  const cues = parseTranscriptText(SAMPLE_SRT);
  const windows = buildCandidateWindows(cues, {
    episodeTitle: 'Why the Bears Offense Could Change Everything',
    minSeconds: 18,
    maxSeconds: 32,
    targetSeconds: 25,
  });
  const selected = selectCandidates(windows, 2);
  assert.equal(selected.length, 2);
  assert.ok(selected[0].score >= selected[1].score);
  const overlap = Math.max(0, Math.min(selected[0].end, selected[1].end) - Math.max(selected[0].start, selected[1].start));
  assert.equal(overlap, 0);
  assert.match(selected[0].reasons.join(' '), /(complete thought|opening hook|question)/);
});

test('word captions are sequential, clip-relative, and one word each', () => {
  const cues = parseTranscriptText(SAMPLE_SRT).slice(0, 2);
  const captions = generateWordCaptions(cues, 0, 11);
  assert.ok(captions.length > 10);
  assert.equal(captions[0].start, 0);
  for (let index = 0; index < captions.length; index += 1) {
    assert.equal(captions[index].text.trim().split(/\s+/).length, 1);
    assert.ok(captions[index].end > captions[index].start);
    if (index > 0) assert.ok(captions[index].start >= captions[index - 1].end - 1e-9);
  }
});
