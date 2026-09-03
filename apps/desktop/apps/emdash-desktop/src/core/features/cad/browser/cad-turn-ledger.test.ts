import { describe, expect, it } from 'vitest';
import { CadTurnLedger } from './cad-turn-ledger';

function clock(start = 1_000) {
  let now = start;
  return { now: () => now, tick: (ms: number) => (now += ms) };
}

describe('CadTurnLedger', () => {
  it('records when a turn starts and ends, keeping the original start', () => {
    const c = clock();
    const ledger = new CadTurnLedger(c.now);
    ledger.apply([['a', 'working']], [['a', 'idle']]);
    c.tick(5_000);
    ledger.apply([['a', 'idle']], [['a', 'working']]);
    expect(ledger.turns.get('a')).toEqual({ startedAt: 1_000, endedAt: 6_000, revealed: false });
  });

  it('reports the earliest pending start across a task and nothing once revealed', () => {
    const c = clock();
    const ledger = new CadTurnLedger(c.now);
    ledger.apply(
      [
        ['a', 'working'],
        ['b', 'idle'],
      ],
      [
        ['a', 'idle'],
        ['b', 'idle'],
      ]
    );
    c.tick(1_000);
    ledger.apply(
      [
        ['a', 'working'],
        ['b', 'working'],
      ],
      [
        ['a', 'working'],
        ['b', 'idle'],
      ]
    );
    c.tick(1_000);
    ledger.apply(
      [
        ['a', 'idle'],
        ['b', 'idle'],
      ],
      [
        ['a', 'working'],
        ['b', 'working'],
      ]
    );
    expect(ledger.pendingSince(['a', 'b'])).toBe(1_000);
    expect(ledger.pendingSince(['b'])).toBe(2_000);
    expect(ledger.pendingSince(['zzz'])).toBeNull();
    ledger.markRevealed(['a', 'b']);
    expect(ledger.pendingSince(['a', 'b'])).toBeNull();
  });

  it('keeps a turn pending while it is still running', () => {
    const ledger = new CadTurnLedger(clock().now);
    ledger.apply([['a', 'working']], [['a', 'idle']]);
    expect(ledger.pendingSince(['a'])).toBeNull();
    ledger.markRevealed(['a']);
    expect(ledger.turns.get('a')?.revealed).toBe(false);
  });

  it('seeds conversations that are already working when a watcher attaches', () => {
    const c = clock(500);
    const ledger = new CadTurnLedger(c.now);
    ledger.seed([
      ['a', 'working'],
      ['b', 'idle'],
    ]);
    expect(ledger.turns.get('a')).toEqual({ startedAt: 500, endedAt: null, revealed: false });
    expect(ledger.turns.has('b')).toBe(false);
    ledger.seed([['a', 'working']]);
    expect(ledger.turns.get('a')?.startedAt).toBe(500);
  });

  it('fingerprints only ended, unrevealed turns', () => {
    const c = clock();
    const ledger = new CadTurnLedger(c.now);
    ledger.apply([['a', 'working']], [['a', 'idle']]);
    expect(ledger.endedFingerprint(['a'])).toBe('');
    c.tick(10);
    ledger.apply([['a', 'idle']], [['a', 'working']]);
    expect(ledger.endedFingerprint(['a'])).toBe('a:1010');
    ledger.markRevealed(['a']);
    expect(ledger.endedFingerprint(['a'])).toBe('');
  });
});
