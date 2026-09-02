export function shouldDismissCadConversationNotice(input: {
  noticeConversationId: string | null;
  selectedConversationId: string | null;
  sessionConversationId: string | null;
  messageCount: number;
}): boolean {
  return (
    input.noticeConversationId !== null &&
    input.noticeConversationId === input.selectedConversationId &&
    input.sessionConversationId === input.selectedConversationId &&
    input.messageCount > 0
  );
}
