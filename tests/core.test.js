import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync, existsSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { freshState, restoreState, shuffle } from '../core.js';

const root = new URL('../', import.meta.url);
const { questions } = JSON.parse(readFileSync(new URL('questions.json', root), 'utf8'));
const mcqs = questions.filter(q => q.type === 'mcq');
const frqs = questions.filter(q => q.type === 'frq');

test('all Unit 2 questions, keys, rubrics, and referenced assets are present', () => {
  assert.deepEqual(questions.map(q => q.id), Array.from({ length: 277 }, (_, i) => i + 1));
  assert.equal(mcqs.length, 183);
  assert.equal(frqs.length, 94);
  for (const q of questions) {
    assert.ok(q.prompt.length, `Question ${q.id} prompt`);
    if (q.type === 'mcq') {
      assert.match(q.options.map(o => o.letter).join(''), /^ABCD(E)?$/);
      assert.ok(q.options.some(o => o.letter === q.correct), `Question ${q.id} answer key`);
    } else assert.ok(q.rubric.length, `Question ${q.id} rubric`);
    const assets = [...q.prompt, ...q.context, ...(q.explanation || []), ...(q.rubric || []), ...(q.options || []).flatMap(o => o.images)];
    for (const image of assets) {
      assert.ok(existsSync(fileURLToPath(new URL(image.src, root))), image.src);
      assert.ok(image.width > 0 && image.height > 0);
    }
    for (const image of [...q.prompt, ...q.context, ...(q.options || []).flatMap(o => o.images)]) {
      assert.doesNotMatch(image.text, /Answer [A-E]\b|Student response earns|Correct\./, `Answer leak in ${image.src}`);
    }
  }
});

test('shuffle preserves every multiple-choice question and changes the order', () => {
  const input = mcqs.map(q => q.id);
  const result = shuffle(input, () => 0);
  assert.notDeepEqual(result, input);
  assert.deepEqual([...result].sort((a, b) => a - b), input);
});

test('first visit has a complete, unanswered Unit 2 round', () => {
  const state = freshState(questions);
  assert.deepEqual(state.answers, {});
  assert.deepEqual(state.drafts, {});
  assert.equal(state.sessions.mcq.order.length, 183);
  assert.equal(state.sessions.frq.order.length, 94);
});

test('restore keeps valid in-mode progress and ignores invalid choices', () => {
  const saved = freshState(questions);
  const mcq = mcqs[0], frq = frqs[0];
  saved.mode = 'frq';
  saved.answers[mcq.id] = mcq.correct;
  saved.answers[mcqs[1].id] = 'Z';
  saved.drafts[frq.id] = 'My response.';
  saved.revealed[frq.id] = true;
  saved.reviewed[frq.id] = true;
  const restored = restoreState(saved, questions);
  assert.equal(restored.answers[mcq.id], mcq.correct);
  assert.equal(restored.answers[mcqs[1].id], undefined);
  assert.equal(restored.drafts[frq.id], 'My response.');
  assert.equal(restored.reviewed[frq.id], true);
});
