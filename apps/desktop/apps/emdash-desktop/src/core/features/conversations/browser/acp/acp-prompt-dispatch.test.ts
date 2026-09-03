import { describe, expect, it, vi } from 'vitest';
import { describeAcpError, dispatchAcpPrompt } from './acp-prompt-dispatch';

describe('ACP prompt dispatch acknowledgement', () => {
  it('reports success only after the session accepts the prompt', async () => {
    const sendPrompt = vi.fn(async () => ({ success: true as const, data: { queued: false } }));

    await expect(
      dispatchAcpPrompt({ sendPrompt }, { text: 'Revise the bracket' })
    ).resolves.toEqual({
      success: true,
    });
    expect(sendPrompt).toHaveBeenCalledWith({ text: 'Revise the bracket' });
  });

  it('reports a missing session without pretending the prompt was sent', async () => {
    await expect(dispatchAcpPrompt(null, { text: 'Revise the bracket' })).resolves.toEqual({
      success: false,
      error: 'The agent session is not connected.',
    });
  });

  it('surfaces both rejected and failed sends', async () => {
    await expect(
      dispatchAcpPrompt(
        {
          sendPrompt: vi.fn(async () => ({
            success: false as const,
            error: { message: 'Provider unavailable' },
          })),
        },
        { text: 'Revise the bracket' }
      )
    ).resolves.toEqual({ success: false, error: 'Provider unavailable' });

    await expect(
      dispatchAcpPrompt(
        {
          sendPrompt: vi.fn(async () => {
            throw new Error('Connection closed');
          }),
        },
        { text: 'Revise the bracket' }
      )
    ).resolves.toEqual({ success: false, error: 'Connection closed' });
  });
});

describe('describeAcpError', () => {
  it('never shows a conversation id as the reason', () => {
    expect(
      describeAcpError({ type: 'conversation_not_found', message: '2cc0c729-430a-470e' })
    ).toEqual({
      type: 'conversation_not_found',
      message: 'The agent session for this chat has ended.',
    });
  });

  it('prefers the underlying cause of a failed prompt', () => {
    expect(
      describeAcpError({
        type: 'prompt_failed',
        cause: { name: 'RequestError', message: "You've hit your session limit" },
      })
    ).toEqual({ type: 'prompt_failed', message: "You've hit your session limit" });
  });

  it('keeps plain messages and falls back to a generic sentence', () => {
    expect(describeAcpError(new Error('Connection closed')).message).toBe('Connection closed');
    expect(describeAcpError({ message: 'Provider unavailable' }).message).toBe(
      'Provider unavailable'
    );
    expect(describeAcpError({ type: 'weird' }).message).toBe('The agent rejected the request.');
    expect(describeAcpError(undefined).message).toBe('The agent rejected the request.');
  });
});
