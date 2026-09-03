import { action, observable } from 'mobx';

export type CadTurnRecord = {
  startedAt: number;
  endedAt: number | null;
  revealed: boolean;
};

export type ConversationStatusSnapshot = ReadonlyArray<readonly [id: string, status: string]>;

/**
 * Which turns have ended and still owe a model reveal, for every conversation
 * in the app. It lives outside any task view so a turn that starts or ends
 * while another project is on screen, or while a pane change remounts the
 * task view, is neither lost nor scanned from the wrong moment.
 */
export class CadTurnLedger {
  readonly turns = observable.map<string, CadTurnRecord>();

  constructor(private readonly now: () => number = Date.now) {}

  /** Fold a status snapshot against the previous one: a turn starts when a conversation begins working and ends when it stops. */
  readonly apply = action(
    (current: ConversationStatusSnapshot, previous?: ConversationStatusSnapshot): void => {
      const before = new Map(previous ?? []);
      for (const [id, status] of current) {
        const was = before.get(id);
        if (status === 'working' && was !== 'working') {
          this.turns.set(id, { startedAt: this.now(), endedAt: null, revealed: false });
        } else if (was === 'working' && status !== 'working') {
          const record = this.turns.get(id);
          this.turns.set(id, {
            startedAt: record?.startedAt ?? this.now(),
            endedAt: this.now(),
            revealed: false,
          });
        }
      }
    }
  );

  /** Conversations already working when a watcher attaches: their turn is assumed to start now. */
  readonly seed = action((current: ConversationStatusSnapshot): void => {
    for (const [id, status] of current) {
      if (status === 'working' && !this.turns.has(id)) {
        this.turns.set(id, { startedAt: this.now(), endedAt: null, revealed: false });
      }
    }
  });

  /** The earliest start among ended, unrevealed turns of the given conversations, or null. */
  pendingSince(ids: Iterable<string>): number | null {
    let since: number | null = null;
    for (const id of ids) {
      const record = this.turns.get(id);
      if (!record || record.endedAt === null || record.revealed) continue;
      since = since === null ? record.startedAt : Math.min(since, record.startedAt);
    }
    return since;
  }

  /** Observable fingerprint of the ended turns for the given conversations, for reactions to key on. */
  endedFingerprint(ids: Iterable<string>): string {
    const parts: string[] = [];
    for (const id of ids) {
      const record = this.turns.get(id);
      if (record?.endedAt !== null && record?.endedAt !== undefined && !record.revealed) {
        parts.push(`${id}:${record.endedAt}`);
      }
    }
    return parts.join('|');
  }

  readonly markRevealed = action((ids: Iterable<string>): void => {
    for (const id of ids) {
      const record = this.turns.get(id);
      if (record && record.endedAt !== null) this.turns.set(id, { ...record, revealed: true });
    }
  });
}

/** The app-wide ledger. */
export const cadTurnLedger = new CadTurnLedger();
