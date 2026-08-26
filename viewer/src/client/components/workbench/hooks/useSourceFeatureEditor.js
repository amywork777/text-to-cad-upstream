import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import {
  requestArtifact,
  requestArtifactStatus,
  requestSourceFeatureModel,
  updateSourceFeatureModel,
} from "@/workbench/cadManifestStore";
import {
  buildSourceEdits,
  decorateSourceFeatures,
  sourceDraftsValid,
  sourceParamKey,
} from "@/workbench/sourceFeatureDrafts";

const ARTIFACT_POLL_MS = 300;
const ARTIFACT_POLL_LIMIT = 1_000;

function delay(ms) {
  return new Promise((resolve) => window.setTimeout(resolve, ms));
}

async function waitForCanonicalArtifact(fileRef) {
  for (let attempt = 0; attempt < ARTIFACT_POLL_LIMIT; attempt += 1) {
    const status = await requestArtifactStatus(fileRef);
    if (status?.state === "ready") return status;
    if (status?.state === "error") {
      throw new Error(String(status?.error || "CAD rebuild failed"));
    }
    await delay(ARTIFACT_POLL_MS);
  }
  throw new Error("CAD rebuild did not finish before the viewer timed out");
}

export default function useSourceFeatureEditor(fileRef) {
  const normalizedFileRef = String(fileRef || "").trim();
  const [state, setState] = useState({ fileRef: "", status: "idle", model: null, error: "" });
  const [drafts, setDrafts] = useState({});
  const requestIdRef = useRef(0);

  const load = useCallback(async ({ quiet = false } = {}) => {
    if (!normalizedFileRef) return null;
    const requestId = ++requestIdRef.current;
    if (!quiet) setState({ fileRef: normalizedFileRef, status: "loading", model: null, error: "" });
    try {
      const model = await requestSourceFeatureModel(normalizedFileRef);
      if (requestId === requestIdRef.current) {
        setState({ fileRef: normalizedFileRef, status: "ready", model, error: "" });
      }
      return model;
    } catch (error) {
      if (requestId === requestIdRef.current) {
        setState({
          fileRef: normalizedFileRef,
          status: "error",
          model: null,
          error: error instanceof Error ? error.message : String(error),
        });
      }
      throw error;
    }
  }, [normalizedFileRef]);

  useEffect(() => {
    setDrafts({});
    if (!normalizedFileRef) {
      setState({ fileRef: "", status: "idle", model: null, error: "" });
      return;
    }
    load().catch(() => {});
  }, [load, normalizedFileRef]);

  const model = state.fileRef === normalizedFileRef ? state.model : null;
  const features = useMemo(
    () => decorateSourceFeatures(model?.features),
    [model?.features]
  );
  const setParameterDraft = useCallback((parameter, value) => {
    const key = sourceParamKey(parameter);
    if (!key) return;
    setDrafts((current) => ({ ...current, [key]: { span: parameter.span, value } }));
  }, []);
  const revert = useCallback(() => setDrafts({}), []);

  const apply = useCallback(async () => {
    if (!model?.supported || !model?.sourceHash || !Object.keys(drafts).length) return false;
    if (!sourceDraftsValid(drafts)) {
      setState((current) => ({ ...current, status: "error", error: "Enter a valid number for every changed dimension." }));
      return false;
    }
    setState((current) => ({ ...current, status: "saving", error: "" }));
    let written = null;
    try {
      written = await updateSourceFeatureModel(normalizedFileRef, {
        expectedHash: model.sourceHash,
        edits: buildSourceEdits(model.source, drafts),
      });
      setState((current) => ({ ...current, status: "rebuilding", error: "" }));
      const result = await requestArtifact(normalizedFileRef, { force: true });
      if (result?.state === "generating") {
        await waitForCanonicalArtifact(normalizedFileRef);
      } else if (!result?.ok || result?.state !== "ready") {
        throw new Error(String(result?.error || "CAD rebuild failed"));
      }
      setDrafts({});
      await load({ quiet: true });
      return true;
    } catch (error) {
      if (written?.sourceHash) {
        try {
          const status = await requestArtifactStatus(normalizedFileRef);
          if (status?.state !== "ready") {
            await updateSourceFeatureModel(normalizedFileRef, {
              expectedHash: written.sourceHash,
              source: model.source,
            });
          }
        } catch {
          // The source route is compare-and-swap guarded. If another edit won the
          // race, do not overwrite it while trying to restore this draft.
        }
      }
      setState((current) => ({
        ...current,
        status: "error",
        error: error instanceof Error ? error.message : String(error),
      }));
      return false;
    }
  }, [drafts, load, model, normalizedFileRef]);

  return {
    status: state.status,
    error: state.error,
    supported: model?.supported === true,
    reason: String(model?.reason || ""),
    source: String(model?.source || ""),
    features,
    drafts,
    hasDrafts: Object.keys(drafts).length > 0,
    draftsValid: sourceDraftsValid(drafts),
    setParameterDraft,
    apply,
    revert,
    reload: load,
  };
}
