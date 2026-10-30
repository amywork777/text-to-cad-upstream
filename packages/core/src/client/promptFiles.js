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
/**
 * How much of a picture one request carries. A view's request crosses its host as one message,
 * and a host carries messages with a ceiling (T3 Code's is 256 KiB); in a tab the body is base64
 * twice over (the JSON, then the tunnel), about 1.8 times this.
 */
const PICTURE_PART_BYTES = 96 * 1024;

const base64 = bytes => {
  let binary = '';
  for (let at = 0; at < bytes.length; at += 0x8000) binary += String.fromCharCode(...bytes.subarray(at, at + 0x8000));
  return btoa(binary);
};

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
      let saved = null;
      // The first part makes the file; each next one adds to it, named as the first was answered.
      for (let at = 0; at < bytes.length || saved === null; at += PICTURE_PART_BYTES) {
        const picture = base64(bytes.subarray(at, at + PICTURE_PART_BYTES));
        const request = saved === null ? { name, picture } : { picture, append: saved.split(/[\\/]/).pop() };
        const body = await answer(await fetchImpl(cadApiUrl('/__cad/prompt-files', { origin }), {
          method: 'POST', headers: { ...headers, 'content-type': 'application/json' }, body: JSON.stringify(request),
        }));
        if (typeof body.picture !== "string") throw new Error("The prompt response has no picture path.");
        saved = body.picture;
      }
      return saved;
    },
    async read(path) {
      const name = String(path).split(/[\\/]/).pop();
      const response = await fetchImpl(cadApiUrl(`/__cad/prompt-files/${encodeURIComponent(name)}`, { origin }), { headers });
      if (!response.ok) throw new Error(`The prompt file ${name} could not be read (${response.status}).`);
      return response.blob();
    },
  };
}
