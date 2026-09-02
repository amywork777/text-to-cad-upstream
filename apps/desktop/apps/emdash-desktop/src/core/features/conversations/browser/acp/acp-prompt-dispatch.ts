import type { PromptInput } from '@emdash/core/runtimes/acp/api/client';

export type AcpPromptDispatchResult = { success: true } | { success: false; error: string };

export interface AcpPromptSender {
  sendPrompt(
    prompt: PromptInput
  ): Promise<{ success: true; data: { queued: boolean } } | { success: false; error: unknown }>;
}

/**
 * A prompt is dispatched only after the ACP runtime explicitly accepts it.
 * Keeping this boundary independent from the composer lets artifact-specific
 * transactions roll back without coupling ordinary chats to CAD state.
 */
export async function dispatchAcpPrompt(
  session: AcpPromptSender | null,
  prompt: PromptInput
): Promise<AcpPromptDispatchResult> {
  if (!session) return { success: false, error: 'The agent session is not connected.' };
  try {
    const result = await session.sendPrompt(prompt);
    return result.success
      ? { success: true }
      : { success: false, error: errorMessage(result.error) };
  } catch (error) {
    return { success: false, error: errorMessage(error) };
  }
}

function errorMessage(error: unknown): string {
  if (error instanceof Error) return error.message;
  if (error && typeof error === 'object' && 'message' in error) {
    const message = (error as { message?: unknown }).message;
    if (typeof message === 'string' && message.trim()) return message;
  }
  return typeof error === 'string' && error.trim() ? error : 'The agent rejected the request.';
}
