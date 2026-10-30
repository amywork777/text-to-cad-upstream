import { cadApiUrl } from './client.js';

/**
 * Prepare a Quick Edit snapshot: small packets inline, larger packets by path, without rendering.
 * `read` fetches a JSON file. `picture` saves a view's PNG as the page drew it and answers its path.
 * @typedef {{ name: string, input: string, views: object[], annotation: object | null }} PromptFilesRequest
 * @typedef {{ snapshot: string, inline?: never } | { inline: string, snapshot?: never }} PromptFiles
 * @param {{ origin?: string, fetch?: typeof globalThis.fetch }} [options]
 * @returns {{ create(request: PromptFilesRequest): Promise<PromptFiles>, read(path: string): Promise<Blob>,
 *   picture(request: { name: string, png: Blob }): Promise<string> }}
 */
export function createHttpPromptFiles({ origin = '', fetch: fetchImpl = globalThis.fetch } = {}) {
  const headers = { 'x-cadgen-viewer': '1' };
  const answer = async response => {
    const body = await response.json().catch(() => null);
    if (!body?.ok) throw new Error(body?.error || `The prompt's files could not be made (${response.status}).`);
    return body;
  };
  return {
    async create(request) {
      const body = await answer(await fetchImpl(cadApiUrl('/__cad/prompt-files', { origin }), {
        method: 'POST', headers: { ...headers, 'content-type': 'application/json' }, body: JSON.stringify({ ...request, acceptInline: true }),
      }));
      if (typeof body.inline === "string") return { inline: body.inline };
      if (typeof body.snapshot === "string") return { snapshot: body.snapshot };
      throw new Error("The prompt response has neither inline JSON nor a snapshot path.");
    },
    async picture({ name, png }) {
      const bytes = new Uint8Array(await png.arrayBuffer());
      let binary = '';
      for (let at = 0; at < bytes.length; at += 0x8000) binary += String.fromCharCode(...bytes.subarray(at, at + 0x8000));
      const body = await answer(await fetchImpl(cadApiUrl('/__cad/prompt-files', { origin }), {
        method: 'POST', headers: { ...headers, 'content-type': 'application/json' }, body: JSON.stringify({ name, picture: btoa(binary) }),
      }));
      if (typeof body.picture === "string") return body.picture;
      throw new Error("The prompt response has no picture path.");
    },
    async read(path) {
      const name = String(path).split(/[\\/]/).pop();
      const response = await fetchImpl(cadApiUrl(`/__cad/prompt-files/${encodeURIComponent(name)}`, { origin }), { headers });
      if (!response.ok) throw new Error(`The prompt file ${name} could not be read (${response.status}).`);
      return response.blob();
    },
  };
}
