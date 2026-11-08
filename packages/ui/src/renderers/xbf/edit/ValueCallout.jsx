import { useEffect, useRef } from "react";
import { modelMapping } from "./sketchDrawing.js";

const BOX_HEIGHT_PX = 22;
const BOX_CLASS = "pointer-events-auto absolute left-0 top-0 z-20 flex items-center gap-1 whitespace-nowrap rounded-md border-2 border-cad-picked bg-background px-1.5 text-xs tabular-nums text-foreground shadow-md";

/**
 * A command's size on the model, beside what it acts on, as SolidWorks' callouts are: a fillet's
 * radius by its first edge, a shell's thickness by its first face. Typed over, Enter or leaving it
 * sets it in the dialog (`callout.onCommit`); Escape puts it back. `callout`: `{ at, label, text,
 * unit, onCommit }`, `at` in the part's millimetres; placed again as the camera moves.
 *
 * @param {{ viewport: { runtimeRef: object, hostRef: object, viewerReadyTick: number }, callout: object | null }} props
 */
export default function ValueCallout({ viewport, callout }) {
  const boxRef = useRef(null);
  const inputRef = useRef(null);
  const shown = useRef("");
  const live = useRef(callout);
  live.current = callout;

  useEffect(() => {
    const host = viewport.hostRef?.current;
    let frame = 0;
    let placed = "";
    const place = () => {
      frame = requestAnimationFrame(place);
      const box = boxRef.current;
      const current = live.current;
      if (!box || !host) return;
      const mapping = current?.at ? modelMapping(viewport.runtimeRef?.current, host.clientWidth || 1, host.clientHeight || 1) : null;
      const key = `${mapping?.key || ""}|${current?.at?.join(",") || ""}`;
      if (key === placed) return;
      placed = key;
      const spot = mapping ? mapping.toScreen(...current.at) : null;
      if (!spot) { box.style.visibility = "hidden"; return; }
      box.style.transform = `translate(${spot[0] + 12}px, ${spot[1] - BOX_HEIGHT_PX / 2}px)`;
      box.style.visibility = "visible";
    };
    frame = requestAnimationFrame(place);
    return () => cancelAnimationFrame(frame);
  }, [viewport.hostRef, viewport.runtimeRef, viewport.viewerReadyTick]);

  // The dialog's value, shown while it is not being typed in.
  useEffect(() => {
    const input = inputRef.current;
    if (input && document.activeElement !== input) input.value = String(callout?.text ?? "");
  }, [callout?.text]);

  if (!callout) return null;
  const commit = () => {
    const text = inputRef.current?.value.trim() || "";
    if (text && text !== shown.current) live.current?.onCommit?.(text);
  };
  return <div ref={boxRef} className={BOX_CLASS} style={{ height: BOX_HEIGHT_PX, visibility: "hidden" }} data-cad-callout=""
    onPointerDown={event => event.stopPropagation()}>
    <span className="text-muted-foreground">{callout.label}</span>
    <input ref={inputRef} inputMode="decimal" aria-label={callout.label} defaultValue={String(callout.text ?? "")}
      className="w-12 bg-transparent text-right text-xs tabular-nums text-foreground outline-none"
      onFocus={event => { shown.current = event.target.value; event.target.select(); }}
      onBlur={commit}
      onKeyDown={event => {
        event.stopPropagation();
        if (event.key === "Enter") { event.preventDefault(); event.currentTarget.blur(); }
        if (event.key === "Escape") { event.preventDefault(); event.currentTarget.value = shown.current; event.currentTarget.blur(); }
      }} />
    {callout.unit ? <span className="text-muted-foreground">{callout.unit}</span> : null}
  </div>;
}
