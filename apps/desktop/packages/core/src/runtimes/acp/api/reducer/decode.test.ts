import type { SessionUpdate } from '@agentclientprotocol/sdk';
import { describe, expect, it } from 'vitest';
import { decodeSessionUpdate } from './decode';

function executeCall(extra: Record<string, unknown>): SessionUpdate {
  return {
    sessionUpdate: 'tool_call',
    toolCallId: 'call-1',
    title: 'ls -la',
    kind: 'execute',
    status: 'in_progress',
    ...extra,
  } as unknown as SessionUpdate;
}

describe('decodeSessionUpdate terminal attachment', () => {
  it('reads the terminal id from a terminal content block', () => {
    const event = decodeSessionUpdate(
      executeCall({ content: [{ type: 'terminal', terminalId: 'call-1' }] })
    );
    expect(event).toMatchObject({ kind: 'tool_call', terminalId: 'call-1' });
  });

  it('prefers an explicit terminalId over content blocks', () => {
    const event = decodeSessionUpdate(
      executeCall({
        terminalId: 'explicit',
        content: [{ type: 'terminal', terminalId: 'from-content' }],
      })
    );
    expect(event).toMatchObject({ kind: 'tool_call', terminalId: 'explicit' });
  });

  it('leaves the terminal id unset without a terminal block', () => {
    const event = decodeSessionUpdate(
      executeCall({ content: [{ type: 'content', content: { type: 'text', text: 'ok' } }] })
    );
    expect(event).toMatchObject({ kind: 'tool_call' });
    expect('terminalId' in event).toBe(false);
  });
});
