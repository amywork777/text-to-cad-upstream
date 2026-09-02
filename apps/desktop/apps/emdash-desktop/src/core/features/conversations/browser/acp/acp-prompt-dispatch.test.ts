import { describe, expect, it, vi } from 'vitest';
import { dispatchAcpPrompt } from './acp-prompt-dispatch';

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
