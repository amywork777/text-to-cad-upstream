import { describe, expect, it } from 'vitest';
import {
  cadConversationTitleFromPrompt,
  isCadConversationPlaceholder,
  nextCadConversationPlaceholder,
} from './cad-conversation-title';

describe('CAD conversation titles', () => {
  it('creates unique temporary titles for chats without a first message', () => {
    expect(nextCadConversationPlaceholder(['Design', 'Review'])).toBe('New chat');
    expect(nextCadConversationPlaceholder(['New chat', 'new chat 2'])).toBe('New chat 3');
  });

  it('recognizes only generated temporary titles', () => {
    expect(isCadConversationPlaceholder('New chat')).toBe(true);
    expect(isCadConversationPlaceholder('New chat 12')).toBe(true);
    expect(isCadConversationPlaceholder('New chassis')).toBe(false);
  });

  it('derives a concise title from the first prompt', () => {
    expect(
      cadConversationTitleFromPrompt('  - Compare aluminum and steel. Then make a table.')
    ).toBe('Compare aluminum and steel.');
    expect(
      cadConversationTitleFromPrompt(
        'Review the current suspension bridge model for manufacturing risks and supplier questions'
      )
    ).toBe('Review the current suspension bridge model for manufacturing…');
  });
});
