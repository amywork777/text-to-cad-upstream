import type { SessionUpdate } from '@agentclientprotocol/sdk';
import type { NormalizedEvent } from '@emdash/core/runtimes/acp/api';

type CodexToolInput = {
  server?: unknown;
  tool?: unknown;
  arguments?: unknown;
};

/** Promote Codex adapter metadata into provider-neutral transcript events. */
export function enrichCodexUpdate(update: NormalizedEvent, raw: SessionUpdate): NormalizedEvent {
  if (update.kind !== 'tool_call' && update.kind !== 'tool_update') return update;

  if (
    update.kind === 'tool_call' &&
    update.toolKind === 'other' &&
    update.title.trim().toLowerCase() === 'image generation'
  ) {
    return { ...update, toolKind: 'image-generation' };
  }

  const input = codexToolInput(raw);
  if (!isMcpToolCall(raw, input)) return update;
  if (typeof input?.server !== 'string' || typeof input.tool !== 'string') return update;
  const inputSummary = summarizeInput(input.arguments);

  // Completion updates can omit arguments. Preserve the safe summary from the
  // start event by letting the normal tool-update reducer merge this update.
  if (update.kind === 'tool_update' && (inputSummary === undefined || update.status === null)) {
    return update;
  }

  return {
    kind: 'mcp_tool',
    toolCallId: update.toolCallId,
    server: input.server,
    tool: input.tool,
    status: update.status,
    parentToolCallId: update.parentToolCallId,
    ...(inputSummary ? { inputSummary } : {}),
  };
}

function codexToolInput(raw: SessionUpdate): CodexToolInput | null {
  const value = (raw as unknown as { rawInput?: unknown }).rawInput;
  return value && typeof value === 'object' ? (value as CodexToolInput) : null;
}

function isMcpToolCall(raw: SessionUpdate, input: CodexToolInput | null): boolean {
  const meta = raw._meta as { is_mcp_tool_call?: unknown } | null | undefined;
  if (meta?.is_mcp_tool_call === true) return true;

  // Codex completion updates do not repeat the metadata marker, but do repeat
  // the structured MCP input. Requiring both names avoids reclassifying a
  // generic dynamic tool that happens to accept one similarly named field.
  return typeof input?.server === 'string' && typeof input.tool === 'string';
}

function summarizeInput(value: unknown): string | undefined {
  const candidates: Array<{ label: string; value: string }> = [];
  const seen = new WeakSet<object>();

  const visit = (current: unknown, depth: number): void => {
    if (!current || typeof current !== 'object' || depth > 4 || candidates.length >= 3) return;
    if (seen.has(current)) return;
    seen.add(current);

    if (Array.isArray(current)) {
      for (const item of current.slice(0, 5)) visit(item, depth + 1);
      return;
    }

    for (const [key, nested] of Object.entries(current)) {
      if (candidates.length >= 3) break;
      if (isSecretLikeKey(key)) continue;

      const label = safeSummaryLabel(key);
      if (label && typeof nested === 'string' && nested.trim()) {
        const text = label === 'URL' ? sanitizeUrl(nested.trim()) : compactText(nested);
        if (text && !candidates.some((candidate) => candidate.value === text)) {
          candidates.push({ label, value: text });
        }
        continue;
      }

      visit(nested, depth + 1);
    }
  };

  visit(value, 0);
  if (candidates.length === 0) return undefined;
  if (candidates.length === 1) return candidates[0]!.value;
  return compactText(candidates.map(({ label, value }) => `${label}: ${value}`).join(' · '), 200);
}

function safeSummaryLabel(key: string): string | null {
  const normalized = normalizeKey(key);
  if (normalized === 'query' || normalized.endsWith('_query')) return 'Query';
  if (
    normalized === 'url' ||
    normalized === 'uri' ||
    normalized.endsWith('_url') ||
    normalized.endsWith('_uri')
  ) {
    return 'URL';
  }
  if (normalized === 'path' || normalized.endsWith('_path')) return 'Path';
  if (
    normalized === 'file' ||
    normalized === 'filename' ||
    normalized.endsWith('_file') ||
    normalized.endsWith('_filename')
  ) {
    return 'File';
  }
  if (normalized === 'title') return 'Title';
  if (normalized === 'name') return 'Name';
  return null;
}

function isSecretLikeKey(key: string): boolean {
  const normalized = normalizeKey(key);
  const parts = normalized.split('_');
  return (
    parts.some((part) =>
      ['token', 'secret', 'password', 'passwd', 'credential', 'credentials', 'cookie'].includes(
        part
      )
    ) ||
    [
      'authorization',
      'auth',
      'private_key',
      'api_key',
      'access_key',
      'session',
      'session_id',
    ].includes(normalized) ||
    normalized.endsWith('_signature') ||
    normalized === 'sig'
  );
}

function normalizeKey(key: string): string {
  return key
    .replace(/([a-z0-9])([A-Z])/g, '$1_$2')
    .replace(/[^a-zA-Z0-9]+/g, '_')
    .replace(/^_+|_+$/g, '')
    .toLowerCase();
}

function compactText(value: string, maxLength = 120): string {
  const text = value.replace(/\s+/g, ' ').trim();
  return text.length > maxLength ? `${text.slice(0, maxLength - 3)}...` : text;
}

function sanitizeUrl(value: string): string {
  if (/^data:/i.test(value)) return '[embedded data]';

  try {
    const url = new URL(value);
    let changed = false;
    if (url.username || url.password) {
      url.username = '';
      url.password = '';
      changed = true;
    }
    for (const key of [...url.searchParams.keys()]) {
      if (!isSecretLikeKey(key)) continue;
      url.searchParams.set(key, 'redacted');
      changed = true;
    }
    if (url.hash && isSecretLikeKey(url.hash.slice(1).split('=', 1)[0] ?? '')) {
      url.hash = 'redacted';
      changed = true;
    }
    return compactText(changed ? url.toString() : value);
  } catch {
    const withoutCredentials = value.replace(/(\/\/)[^/@\s]+@/, '$1');
    const redacted = withoutCredentials.replace(
      /([?&#])([^=&#]+)=([^&#]*)/g,
      (match, separator: string, key: string) =>
        isSecretLikeKey(key) ? `${separator}${key}=redacted` : match
    );
    return compactText(redacted);
  }
}
