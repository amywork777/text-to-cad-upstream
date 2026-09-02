const PLACEHOLDER_TITLE = 'New chat';
const MAX_GENERATED_TITLE_LENGTH = 64;

export function nextCadConversationPlaceholder(titles: readonly string[]): string {
  const used = new Set(titles.map((title) => title.trim().toLowerCase()));
  if (!used.has(PLACEHOLDER_TITLE.toLowerCase())) return PLACEHOLDER_TITLE;

  let index = 2;
  while (used.has(`${PLACEHOLDER_TITLE.toLowerCase()} ${index}`)) index += 1;
  return `${PLACEHOLDER_TITLE} ${index}`;
}

export function isCadConversationPlaceholder(title: string): boolean {
  return /^new chat(?: (?:[2-9]|[1-9]\d+))?$/i.test(title.trim());
}

export function cadConversationTitleFromPrompt(prompt: string): string {
  const normalized = prompt
    .replace(/^\s*[-#>*]+\s*/gm, '')
    .replace(/\s+/g, ' ')
    .trim();
  if (!normalized) return PLACEHOLDER_TITLE;

  const sentence = normalized.match(/^.*?[.!?](?:\s|$)/)?.[0]?.trim() ?? normalized;
  if (sentence.length <= MAX_GENERATED_TITLE_LENGTH) return sentence;
  const prefix = sentence.slice(0, MAX_GENERATED_TITLE_LENGTH - 1).trimEnd();
  const lastWordBoundary = prefix.lastIndexOf(' ');
  return `${(lastWordBoundary > 0 ? prefix.slice(0, lastWordBoundary) : prefix).trimEnd()}…`;
}
