import type { SessionUpdate } from '@agentclientprotocol/sdk';
import type { NormalizedEvent } from '@emdash/core/runtimes/acp/api';
import { describe, expect, it } from 'vitest';
import { enrichCodexUpdate } from './acp-transform';

function makeToolCall(
  overrides: Partial<NormalizedEvent & { kind: 'tool_call' }> = {}
): NormalizedEvent {
  return {
    kind: 'tool_call',
    toolCallId: 'tc-1',
    title: 'Run tool',
    toolKind: 'other',
    status: 'in_progress',
    parentToolCallId: null,
    diffs: [],
    ...overrides,
  };
}

function makeToolUpdate(
  overrides: Partial<NormalizedEvent & { kind: 'tool_update' }> = {}
): NormalizedEvent {
  return {
    kind: 'tool_update',
    toolCallId: 'tc-1',
    title: null,
    toolKind: null,
    status: 'completed',
    parentToolCallId: null,
    diffs: [],
    ...overrides,
  };
}

function makeRaw(input?: unknown, meta?: Record<string, unknown>): SessionUpdate {
  return {
    sessionUpdate: 'tool_call',
    toolCallId: 'tc-1',
    title: 'Run tool',
    ...(input !== undefined ? { rawInput: input } : {}),
    ...(meta !== undefined ? { _meta: meta } : {}),
  } as unknown as SessionUpdate;
}

describe('enrichCodexUpdate', () => {
  it('is identity for non-tool events', () => {
    const update: NormalizedEvent = {
      kind: 'message',
      role: 'assistant',
      messageId: 'a-1',
      text: 'done',
    };
    expect(enrichCodexUpdate(update, makeRaw())).toBe(update);
  });

  it('promotes Codex MCP metadata and raw input to an MCP tool event', () => {
    const update = makeToolCall({ parentToolCallId: 'parent-1' });
    const raw = makeRaw(
      { server: 'browser', tool: 'open', arguments: { url: 'https://example.test' } },
      { is_mcp_tool_call: true }
    );

    expect(enrichCodexUpdate(update, raw)).toEqual({
      kind: 'mcp_tool',
      toolCallId: 'tc-1',
      server: 'browser',
      tool: 'open',
      status: 'in_progress',
      parentToolCallId: 'parent-1',
      inputSummary: 'https://example.test',
    });
  });

  it('recognizes completion updates from their repeated structured MCP input', () => {
    const update = makeToolUpdate({ status: 'completed' });
    const raw = makeRaw({ server: 'notion', tool: 'search', arguments: { query: 'CAD' } });

    expect(enrichCodexUpdate(update, raw)).toMatchObject({
      kind: 'mcp_tool',
      server: 'notion',
      tool: 'search',
      status: 'completed',
      inputSummary: 'CAD',
    });
  });

  it('summarizes only safe high-signal MCP fields and recursively skips secrets', () => {
    const update = makeToolCall();
    const raw = makeRaw(
      {
        server: 'notion',
        tool: 'search',
        arguments: {
          request: { query: 'CAD standards' },
          auth: { token: 'secret-token', nested: { name: 'must-not-leak' } },
          payload: { body: 'arbitrary raw body' },
        },
      },
      { is_mcp_tool_call: true }
    );

    const result = enrichCodexUpdate(update, raw);
    expect(result).toMatchObject({ kind: 'mcp_tool', inputSummary: 'CAD standards' });
    expect(JSON.stringify(result)).not.toContain('secret-token');
    expect(JSON.stringify(result)).not.toContain('must-not-leak');
    expect(JSON.stringify(result)).not.toContain('arbitrary raw body');
  });

  it('redacts secrets embedded in MCP URL summaries', () => {
    const update = makeToolCall();
    const raw = makeRaw(
      {
        server: 'browser',
        tool: 'open',
        arguments: {
          url: 'https://amy:password@example.test/spec?view=full&access_token=secret-token',
        },
      },
      { is_mcp_tool_call: true }
    );

    expect(enrichCodexUpdate(update, raw)).toMatchObject({
      kind: 'mcp_tool',
      inputSummary: 'https://example.test/spec?view=full&access_token=redacted',
    });
  });

  it('does not surface arbitrary MCP argument payloads', () => {
    const update = makeToolCall();
    const raw = makeRaw(
      {
        server: 'vendor',
        tool: 'mutate',
        arguments: { payload: { body: 'private arbitrary payload' }, password: 'secret' },
      },
      { is_mcp_tool_call: true }
    );

    expect(enrichCodexUpdate(update, raw)).toEqual({
      kind: 'mcp_tool',
      toolCallId: 'tc-1',
      server: 'vendor',
      tool: 'mutate',
      status: 'in_progress',
      parentToolCallId: null,
    });
  });

  it('keeps status-less MCP updates generic even when safe arguments repeat', () => {
    const update = makeToolUpdate({ title: null, status: null });
    const raw = makeRaw({
      server: 'browser',
      tool: 'open',
      arguments: { url: 'https://example.test' },
    });

    expect(enrichCodexUpdate(update, raw)).toBe(update);
  });

  it('does not promote malformed MCP metadata without server and tool names', () => {
    const update = makeToolCall();
    expect(
      enrichCodexUpdate(update, makeRaw({ server: 'browser' }, { is_mcp_tool_call: true }))
    ).toBe(update);
  });

  it('stamps image-generation starts with a semantic tool kind', () => {
    const update = makeToolCall({ title: 'Image generation', toolKind: 'other' });
    expect(enrichCodexUpdate(update, makeRaw())).toEqual({
      ...update,
      toolKind: 'image-generation',
    });
  });

  it('leaves ordinary tool calls unchanged', () => {
    const update = makeToolCall({ title: 'Guardian Review', toolKind: 'think' });
    expect(enrichCodexUpdate(update, makeRaw())).toBe(update);
  });
});
