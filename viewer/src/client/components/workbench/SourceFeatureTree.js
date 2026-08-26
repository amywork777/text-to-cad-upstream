import { useEffect, useMemo, useState } from "react";
import {
  Box,
  Check,
  ChevronDown,
  ChevronRight,
  Circle,
  LoaderCircle,
  PencilRuler,
  RotateCcw,
  RotateCw,
} from "lucide-react";

import { cn } from "@/ui/utils";
import { featureParameterRows, sourceParamKey } from "@/workbench/sourceFeatureDrafts";
import { Button } from "../ui/button";

const groupLabelClasses = "px-2 pb-1 pt-2 text-[10px] font-medium uppercase tracking-wide text-sidebar-foreground/45";

function FeatureIcon({ feature, sketch = false }) {
  if (sketch) return <PencilRuler className="size-3.5" strokeWidth={1.7} />;
  if (feature?.type?.includes("Revolve")) return <RotateCw className="size-3.5" strokeWidth={1.7} />;
  if (feature?.type === "Hole") return <Circle className="size-3.5" strokeWidth={1.7} />;
  return <Box className="size-3.5" strokeWidth={1.7} />;
}

function displayParameterName(name) {
  return String(name || "")
    .replace(/_/g, " ")
    .replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function parameterUnit(parameter) {
  return String(parameter?.name || "") === "revolution_arc" ? "deg" : "mm";
}

export default function SourceFeatureTree({ editor }) {
  const features = Array.isArray(editor?.features) ? editor.features : [];
  const [selectedNodeId, setSelectedNodeId] = useState("");
  const [expandedIds, setExpandedIds] = useState(() => new Set());

  useEffect(() => {
    const ids = new Set(features.flatMap((feature) => [feature.id, feature.sketch?.id].filter(Boolean)));
    setSelectedNodeId((current) => ids.has(current) ? current : String(features[0]?.id || ""));
    setExpandedIds((current) => {
      const next = new Set([...current].filter((id) => ids.has(id)));
      for (const feature of features) {
        if (feature.sketch?.id) next.add(feature.id);
      }
      return next;
    });
  }, [features]);

  const selectedFeature = useMemo(
    () => features.find((feature) => feature.id === selectedNodeId || feature.sketch?.id === selectedNodeId) || null,
    [features, selectedNodeId]
  );
  const parameters = useMemo(
    () => featureParameterRows(selectedFeature, selectedNodeId),
    [selectedFeature, selectedNodeId]
  );
  const busy = editor?.status === "saving" || editor?.status === "rebuilding";

  if (editor?.status === "loading") {
    return (
      <div className="px-2 py-3 text-xs text-sidebar-foreground/55">
        <LoaderCircle className="mr-1.5 inline size-3.5 animate-spin" />
        Reading design history…
      </div>
    );
  }
  if (!editor?.supported) {
    return editor?.status === "error" ? (
      <div className="mx-2 my-2 rounded-md border border-destructive/30 bg-destructive/5 px-2.5 py-2 text-xs text-destructive">
        {editor.error}
      </div>
    ) : null;
  }

  return (
    <div className="border-b border-sidebar-border/70 pb-2" data-source-feature-tree>
      <div className={groupLabelClasses}>Design</div>
      {!features.length ? (
        <div className="px-2 pb-2 text-xs text-sidebar-foreground/55">
          No editable construction features found.
        </div>
      ) : (
        <div className="space-y-px px-1">
          {features.map((feature) => {
            const expanded = expandedIds.has(feature.id);
            const hasSketch = Boolean(feature.sketch);
            return (
              <div key={feature.id}>
                <div className="flex min-w-0 items-center">
                  <button
                    type="button"
                    className="grid size-6 shrink-0 place-items-center rounded-sm text-sidebar-foreground/50 hover:bg-sidebar-accent"
                    aria-label={`${expanded ? "Collapse" : "Expand"} ${feature.label}`}
                    disabled={!hasSketch}
                    onClick={() => {
                      if (!hasSketch) return;
                      setExpandedIds((current) => {
                        const next = new Set(current);
                        if (next.has(feature.id)) next.delete(feature.id);
                        else next.add(feature.id);
                        return next;
                      });
                    }}
                  >
                    {hasSketch ? (expanded ? <ChevronDown className="size-3.5" /> : <ChevronRight className="size-3.5" />) : null}
                  </button>
                  <button
                    type="button"
                    className={cn(
                      "flex h-7 min-w-0 flex-1 items-center gap-2 rounded-md px-2 text-left text-xs",
                      selectedNodeId === feature.id
                        ? "bg-sidebar-accent font-medium text-sidebar-accent-foreground"
                        : "text-sidebar-foreground hover:bg-sidebar-accent/60"
                    )}
                    onClick={() => setSelectedNodeId(feature.id)}
                  >
                    <FeatureIcon feature={feature} />
                    <span className="truncate">{feature.label}</span>
                  </button>
                </div>
                {hasSketch && expanded ? (
                  <button
                    type="button"
                    className={cn(
                      "ml-8 flex h-7 w-[calc(100%-2.25rem)] min-w-0 items-center gap-2 rounded-md px-2 text-left text-xs",
                      selectedNodeId === feature.sketch.id
                        ? "bg-sidebar-accent font-medium text-sidebar-accent-foreground"
                        : "text-sidebar-foreground hover:bg-sidebar-accent/60"
                    )}
                    onClick={() => setSelectedNodeId(feature.sketch.id)}
                  >
                    <FeatureIcon sketch />
                    <span className="truncate">{feature.sketch.label}</span>
                  </button>
                ) : null}
              </div>
            );
          })}
        </div>
      )}

      {selectedFeature ? (
        <div className="mx-2 mt-3 rounded-md border border-sidebar-border/70 bg-sidebar-accent/15">
          <div className="border-b border-sidebar-border/60 px-2.5 py-2 text-[11px] font-medium text-sidebar-foreground">
            {selectedNodeId === selectedFeature.sketch?.id ? selectedFeature.sketch.label : selectedFeature.label}
            <span className="ml-1.5 font-normal text-sidebar-foreground/45">Dimensions</span>
          </div>
          <div className="space-y-2 p-2.5">
            {!parameters.length ? (
              <div className="text-[11px] text-sidebar-foreground/50">No literal dimensions to edit.</div>
            ) : parameters.map((parameter) => {
              const key = sourceParamKey(parameter);
              const draft = editor.drafts?.[key];
              return (
                <label key={`${parameter.group || "feature"}:${key}`} className="grid grid-cols-[minmax(0,1fr)_5.75rem] items-center gap-2 text-[11px]">
                  <span className="min-w-0 truncate text-sidebar-foreground/65" title={parameter.group ? `${parameter.group} · ${displayParameterName(parameter.name)}` : undefined}>
                    {parameter.group ? <span className="text-sidebar-foreground/35">{parameter.group} · </span> : null}
                    {displayParameterName(parameter.name)}
                  </span>
                  <span className="flex items-center rounded-md border border-input bg-background focus-within:ring-1 focus-within:ring-ring">
                    <input
                      type="number"
                      step="any"
                      className="h-7 min-w-0 flex-1 bg-transparent px-2 text-right tabular-nums outline-none"
                      value={draft ? draft.value : String(parameter.value)}
                      disabled={busy}
                      onChange={(event) => editor.setParameterDraft(parameter, event.target.value)}
                    />
                    <span className="pr-1.5 text-[9px] text-muted-foreground">{parameterUnit(parameter)}</span>
                  </span>
                </label>
              );
            })}
          </div>
        </div>
      ) : null}

      {editor?.error ? (
        <div className="mx-2 mt-2 rounded-md border border-destructive/30 bg-destructive/5 px-2.5 py-2 text-[11px] text-destructive">
          {editor.error}
        </div>
      ) : null}

      {editor?.hasDrafts ? (
        <div className="mx-2 mt-2 flex items-center justify-end gap-1.5">
          <Button type="button" variant="ghost" size="sm" className="h-7 px-2 text-[11px]" disabled={busy} onClick={editor.revert}>
            <RotateCcw className="mr-1 size-3" /> Revert
          </Button>
          <Button type="button" size="sm" className="h-7 px-2 text-[11px]" disabled={busy || !editor.draftsValid} onClick={editor.apply}>
            {busy ? <LoaderCircle className="mr-1 size-3 animate-spin" /> : <Check className="mr-1 size-3" />}
            {editor.status === "rebuilding" ? "Rebuilding…" : editor.status === "saving" ? "Saving…" : "Apply"}
          </Button>
        </div>
      ) : null}
    </div>
  );
}
