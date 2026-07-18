import test from 'node:test';
import assert from 'node:assert/strict';
import {
  assignAudioFirstTiers,
  mergeTranscriptionChunks,
} from '../scripts/generate-audio-first-shorts.mjs';

test('merges chunk timestamps with stable offsets', () => {
  const merged = mergeTranscriptionChunks([
    {
      offset: 0,
      data: {
        segments: [{ start: 0, end: 3, text: 'Opening thought.' }],
        words: [{ start: 0, end: 1, word: 'Opening' }, { start: 1, end: 2, word: 'thought.' }],
      },
    },
    {
      offset: 900,
      data: {
        segments: [{ start: 1, end: 4, text: 'Second section.' }],
        words: [{ start: 1, end: 2, word: 'Second' }, { start: 2, end: 3, word: 'section.' }],
      },
    },
  ]);
  assert.equal(merged.segments[1].start, 901);
  assert.equal(merged.words[2].start, 901);
  assert.equal(merged.text, 'Opening thought. Second section.');
});

test('assigns three premium slots and five rapid slots', () => {
  const candidates = Array.from({ length: 8 }, (_, index) => ({
    rank: index + 1,
    text: index === 1
      ? 'The route concept attacks zone coverage with motion and spacing.'
      : `Complete editorial thought number ${index + 1}.`,
  }));
  const tiered = assignAudioFirstTiers(candidates, 3);
  assert.equal(tiered.filter((item) => item.tier !== 'rapid').length, 3);
  assert.equal(tiered.filter((item) => item.tier === 'rapid').length, 5);
  assert.equal(tiered[1].tier, 'explainer');
  assert.equal(tiered[0].tier, 'flagship');
});

test('does not force tactical treatment on general commentary', () => {
  const tiered = assignAudioFirstTiers([
    { rank: 1, text: 'This is a strong opinion about the season.' },
    { rank: 2, text: 'The community benefits when local support stays local.' },
    { rank: 3, text: 'A bar becomes part of the football experience.' },
    { rank: 4, text: 'Another complete thought.' },
  ], 3);
  assert.deepEqual(tiered.map((item) => item.tier), ['flagship', 'flagship', 'flagship', 'rapid']);
});
