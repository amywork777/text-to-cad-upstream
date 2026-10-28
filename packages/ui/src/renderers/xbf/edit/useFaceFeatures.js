import { useCallback, useEffect, useMemo, useRef, useState } from "react";

const NONE = Object.freeze({});

/**
 * Which feature made each face picked in the workspace, as the edit service says (`client.editFace`,
 * `/__cad/edit/face`): from the engine's record of the call that made it (`made_by`) for a model's
 * document, from the trace's map of the faces (`face_features.py`) for a file. Each face is asked once
 * per reading of the part (`version`: the files the page read it from, the builds, the document on
 * screen), with the files' hashes (`files`), so a part that changed since names no feature; a face the
 * service says is `stale` (its part being built again) names none, and is asked again once the reading
 * moves on.
 *
 * `shown`: whether a face is named at all (the workspace up on a part, its model the one read: never
 * an assembly, the rollback bar's body, or a model loading). `numbers`: the faces picked, by their
 * number on the part.
 *
 * Returns `faces`, the map `faceChips.js` and `selectionBar.js` read (`{ faceFeatures }`: a face's
 * number to its feature's key), of the faces answered, or null while none is to be named; and
 * `featureOf(number)`, a face's feature asked now (a double-click on one not yet picked), a promise of
 * its key or null.
 *
 * @param {{ client: object | null, file: string, shown: boolean, version: string,
 *   files?: Record<string, string> | null, numbers: number[] }} options
 */
export function useFaceFeatures({ client, file, shown, version, files = null, numbers }) {
  const supported = typeof client?.editFace === "function";
  // The answers of this reading: `${version}\n${file}` and, by face number, its feature's key (null: none).
  const [held, setHeld] = useState(() => ({ key: "", features: new Map() }));
  const key = `${version}\n${file}`;
  const asked = useRef(new Map());
  const filesRef = useRef(files);
  filesRef.current = files;
  // The reading now: a reply to a reading gone by (a version that moved on while it was asked) is let go.
  const keyRef = useRef(key);
  keyRef.current = key;
  const ask = useCallback((number) => {
    const pending = asked.current.get(`${key}|${number}`);
    if (pending) return pending;
    const promise = Promise.resolve(client.editFace({ file, face: number, files: filesRef.current || null }))
      .then(reply => {
        if (keyRef.current !== key) return null;
        const found = reply?.ok ? reply.faceFeature : null;
        // A stale answer is no answer: the face is asked again once the part reads anew.
        if (!found || found.stale) { asked.current.delete(`${key}|${number}`); return null; }
        const feature = typeof found.feature === "string" && found.feature ? found.feature : null;
        setHeld(current => ({ key, features: new Map(current.key === key ? current.features : []).set(number, feature) }));
        return feature;
      }, () => { asked.current.delete(`${key}|${number}`); return null; });
    asked.current.set(`${key}|${number}`, promise);
    return promise;
  }, [client, file, key]);
  const wanted = numbers.join(",");
  useEffect(() => {
    if (!supported || !shown || !file) return;
    for (const number of numbers) void ask(number);
    // The faces by their numbers, asked again for a new reading.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [supported, shown, file, wanted, ask]);
  // A new reading forgets the last one's answers.
  useEffect(() => {
    for (const each of asked.current.keys()) if (!each.startsWith(`${key}|`)) asked.current.delete(each);
  }, [key]);
  const faces = useMemo(() => {
    if (!shown || held.key !== key) return null;
    const map = {};
    for (const [number, feature] of held.features) if (feature) map[String(number)] = feature;
    return { faceFeatures: Object.keys(map).length ? map : NONE };
  }, [shown, held, key]);
  const featureOf = useCallback(number => (supported && shown && file ? ask(number) : Promise.resolve(null)), [supported, shown, file, ask]);
  return { faces, featureOf };
}
