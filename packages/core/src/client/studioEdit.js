// Studio's edit mode on the client (studio-base, not Jake's text-to-cad): its methods, which
// `createCadClient` spreads into the client it makes (`client.js`), over the server's
// `/api/v1/local/edit/*` (`cad_server/viewer/studio.py`). Their types are `studioEditTypes.ts`.

const JSON_POST = Object.freeze({ 'content-type': 'application/json', 'x-cad-viewer': '1' });

/** The edit-mode methods of a client, over its `request` (`client.js`). */
export function studioEditMethods(request) {
  return {
    // Edit mode (`cad/edit`): the part script behind `file` read as a design, and one number
    // of it changed. A cold read runs the part once, so its bound is far past the house 10 s.
    editState(file, files = null, { signal, probe = false, bar = null } = {}) {
      if (!file) return Promise.reject(new Error('Missing file'));
      // `probe`: only whether the file has a part script to edit, answered without running it.
      // `bar`: where the rollback bar is, said again if the part has changed.
      return request('/api/v1/local/edit/state', { body: probe ? { file, probe: true } : { file, files, ...(bar ? { bar } : {}) }, signal, method: 'POST',
        timeoutMs: probe ? 15_000 : 200_000, operation: 'edit', headers: JSON_POST });
    },
    editChange(change, { signal } = {}) {
      return request('/api/v1/local/edit/change', { body: change, signal, method: 'POST', timeoutMs: 200_000, operation: 'edit', headers: JSON_POST });
    },
    // The feature that made a face of `file`, with the hashes the page read the part from (`files`).
    editFace({ file, face, files = null } = {}, { signal } = {}) {
      if (!file) return Promise.reject(new Error('Missing file'));
      return request('/api/v1/local/edit/face', { body: { file, face, ...(files ? { files } : {}) }, signal, method: 'POST', timeoutMs: 200_000,
        operation: 'edit', headers: JSON_POST });
    },
  };
}
