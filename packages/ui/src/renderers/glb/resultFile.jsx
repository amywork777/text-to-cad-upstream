// Studio's results viewer (studio-base): the FEA and CAM results a GLB file can carry, kept out of
// GlbRenderer.jsx, which hands its file here and is handed back the surface to draw.
import { useEffect, useMemo, useState } from "react";
import { entryMeshAssetUrl } from "@cad/core/lib/entryAssets.js";
import { useWorkspaceDocument } from "../workspace/useWorkspaceDocument.js";
import { carriesFeaResult } from "./fea/generator.js";
import { useCamView } from "./cam/useCamResult.jsx";
import { useGlbScene } from "./useGlbScene.js";

// The FEA result viewer (`feaView.jsx`), once a result has loaded it, for every result after it.
let feaView = null;
/** Loads the FEA result viewer: its own chunk, which a plain GLB never fetches. */
export const loadFeaView = () => import("./feaView.jsx").then((module) => { feaView = module; return module; });

/**
 * The FEA result viewer for a scene that carries a result, loaded the first time one does; `pending` while it
 * loads. A plain GLB's is null. Should the chunk fail to load, `error` says so, and the result is not drawn as
 * the plain GLB it is not.
 */
function useFeaView(root) {
  const wanted = useMemo(() => carriesFeaResult(root), [root]);
  const [kit, setKit] = useState(feaView);
  const [error, setError] = useState(null);
  useEffect(() => {
    if (!wanted || kit || error) return undefined;
    let live = true;
    loadFeaView().then((module) => { if (live) setKit(module); }, (failure) => { if (live) setError(failure); });
    return () => { live = false; };
  }, [wanted, kit, error]);
  return { kit: wanted && kit ? kit : null, pending: wanted && !kit && !error, error: wanted ? error : null };
}

/**
 * A GLB file: its scene, loaded once, drawn by the FEA result viewer when it carries a result (`FeaSurface.jsx`,
 * its own surface over the same shell) and by the GLB surface (`Surface`, GlbRenderer's) otherwise. A result waits
 * for its viewer as the file loading, so it is framed once, as that viewer draws it.
 *
 * A CAM result (a plan's `result.glb`, its job the `result.json` beside it; or a 0.10 `.cam.glb`) has a viewer of
 * its own (`cam/useCamResult.jsx`), loaded as its own chunk; it waits for it and for the job as the file loading, so
 * it is framed once, as the viewer draws it. A chunk that fails, a job that will not read, or one that is damaged, is
 * the file failing: drawn as a plain GLB, a result would hide its verdict. So the surface is handed the load as the
 * results make it (`loaded`: no scene, and still busy, while a viewer or a job loads; failed with its error) and the
 * CAM viewer and job (`cam`: `{ cv, job }`, nulls for any other GLB).
 */
export function GlbResultFile({ view, data, surface }) {
  const document = useWorkspaceDocument({ view, data });
  const loaded = useGlbScene({ entry: document.entry, resources: document.client.resources });
  const { kit: fv, pending, error } = useFeaView(loaded.scene?.document?.scene);
  if (fv) return <fv.FeaSurface view={view} document={document} loaded={loaded} fv={fv} />;
  return <CamResultSurface view={view} document={document} loaded={loaded} pending={pending} feaError={error} surface={surface} />;
}

function CamResultSurface({ view, document, loaded, pending: feaPending, feaError, surface: Surface }) {
  const { kit: cv, cam: job, pending: camPending, failed: camFailed } = useCamView(loaded.scene?.document,
    { resources: document.client.resources, url: entryMeshAssetUrl(document.entry) });
  const pending = feaPending || camPending;
  const shown = {
    ...loaded,
    scene: pending || feaError || camFailed ? null : loaded.scene,
    error: loaded.error || feaError || camFailed,
    busy: loaded.busy || pending
  };
  return <Surface view={view} document={document} loaded={shown} cam={{ cv, job }} />;
}
