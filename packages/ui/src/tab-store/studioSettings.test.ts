import { expect, test } from 'vitest';
import { readTabRecord } from './tabRecord.js';
import { OPENED_FROM_LIMIT } from './studioSettings.js';

test('edit mode\'s settings: Manual or AI, and each part\'s way back an assembly\'s file and title, the latest twenty', () => {
  const settings = (value: Record<string, unknown>) => readTabRecord({ version: 2, settings: value, files: {} }).settings;
  expect(settings({ editLayout: 'ai' }).editLayout).toBe('ai');
  expect(settings({ editLayout: 'sketch' }).editLayout).toBe('manual');
  // A way back to the part itself, one with no file, or one that is not a record is none.
  expect(settings({ openedFrom: {
    '/m/post.step': { file: '/m/stack.step', title: 'Stack' }, '/m/self.step': { file: '/m/self.step', title: 'Self' },
    '/m/none.step': { title: 'No file' }, '/m/junk.step': 'stack',
  } }).openedFrom).toEqual({ '/m/post.step': { file: '/m/stack.step', title: 'Stack' } });
  const many = Object.fromEntries(Array.from({ length: 30 }, (_, index) => [`/m/part${index}.step`, { file: '/m/stack.step', title: 'Stack' }]));
  expect(OPENED_FROM_LIMIT).toBe(20);
  expect(Object.keys(settings({ openedFrom: many }).openedFrom)).toEqual(Object.keys(many).slice(-20));
});
