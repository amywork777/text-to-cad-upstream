import { describe, expect, it } from 'vitest';
import { shouldDismissCadConversationNotice } from './cad-conversation-notice';

describe('CAD conversation notice', () => {
  it('stays visible while the previous chat session is being replaced', () => {
    expect(
      shouldDismissCadConversationNotice({
        noticeConversationId: 'new-chat',
        selectedConversationId: 'new-chat',
        sessionConversationId: 'previous-chat',
        messageCount: 4,
      })
    ).toBe(false);
  });

  it('dismisses after the new chat receives its first message', () => {
    expect(
      shouldDismissCadConversationNotice({
        noticeConversationId: 'new-chat',
        selectedConversationId: 'new-chat',
        sessionConversationId: 'new-chat',
        messageCount: 1,
      })
    ).toBe(true);
  });
});
