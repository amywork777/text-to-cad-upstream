import { useEffect, useId, useRef, useState } from "react";
import { ScrollArea } from "@text-to-cad/ui/primitives/scroll-area";
import { cn } from "@text-to-cad/ui/utils";
import { WORKSPACE_SURFACE_CLASS } from "../../../lib/floatingSurface.js";
import { findCommands } from "./commandSearch.js";

// A result, as a toolbar button's colors are: the workspace's pale blue under the pointer, its deeper one for the one chosen.
// A command the toolbar shows dimmed is dimmed, and the pointer passes over it as over the toolbar's dimmed button.
const ROW_CLASS = "flex h-7 w-full min-w-0 cursor-default items-center gap-2 rounded-sm px-2 text-xs text-foreground aria-disabled:opacity-40 [&_svg]:size-5 [&_svg]:shrink-0";
const HOVER_CLASS = "hover:bg-cad-ws-hover";
const CHOSEN_CLASS = "bg-cad-ws-selected hover:bg-cad-ws-selected";

/**
 * Command search, the box S opens (`useEditShortcuts.js`): a text field over the commands the toolbar has,
 * found by name and by what other tools call them (`commandSearch.js`), each as the toolbar draws its button.
 * Enter runs the first result, or the one the arrow keys moved to; Escape, a press outside, or focus leaving
 * puts the box away, and focus goes back where it was. It floats under the toolbar at the canvas's top centre
 * (its parent holds the toolbar and is positioned), in the workspace's white card.
 *
 * A command the toolbar shows dimmed is listed dimmed, says why (the toolbar's own reason) while it is the
 * choice, and runs nothing. A command the toolbar has no button for is not listed.
 *
 * @param {{ items: { id: string, label: string, icon?: import("react").ReactNode, disabled?: boolean,
 *   description?: string, run: () => void }[], sketching?: boolean, onClose: () => void }} props
 *   `items`: the toolbar's buttons as the search may run them, by `id`, whichever tab each is on; `label`
 *   is the toolbar's name for one now; `run` does what pressing its button does. `sketching`: a sketch is open.
 */
export default function CommandSearchBox({ items, sketching = false, onClose }) {
  const [query, setQuery] = useState("");
  const [chosen, setChosen] = useState(0);
  // Where focus was as the box opened.
  const [before] = useState(() => document.activeElement);
  const box = useRef(null);
  const field = useRef(null);
  const id = useId();

  const byId = new Map(items.map(item => [item.id, item]));
  const labels = Object.fromEntries(items.map(item => [item.id, item.label]));
  const rows = findCommands(query, { sketching, labels }).flatMap(result => (byId.has(result.id) ? [{ ...result, item: byId.get(result.id) }] : []));
  // The choice stays on the list as the list changes under it.
  const at = Math.min(chosen, Math.max(rows.length - 1, 0));
  const row = rows[at] || null;

  // The text field has focus while the box stands, and focus goes back where it was when the box goes, unless it was taken elsewhere.
  useEffect(() => {
    field.current?.focus();
    return () => {
      const now = document.activeElement;
      if ((!now || now === document.body) && before instanceof HTMLElement && before !== document.body && before.isConnected) before.focus();
    };
  }, [before]);
  // A press anywhere else puts the box away, though the press itself goes on: a press on the canvas may keep focus where it is.
  useEffect(() => {
    const away = event => { if (!box.current?.contains(event.target)) onClose(); };
    window.addEventListener("pointerdown", away, true);
    return () => window.removeEventListener("pointerdown", away, true);
  }, [onClose]);
  // The choice stays in view in a long list.
  useEffect(() => { box.current?.querySelector(`[data-index="${at}"]`)?.scrollIntoView?.({ block: "nearest" }); }, [at]);

  const run = each => {
    if (!each || each.item.disabled) return;
    onClose();
    each.item.run();
  };
  const onKeyDown = event => {
    if (event.nativeEvent.isComposing) return;
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      if (rows.length) setChosen((at + (event.key === "ArrowDown" ? 1 : rows.length - 1)) % rows.length);
    } else if (event.key === "Enter") {
      event.preventDefault();
      run(row);
    } else if (event.key === "Escape") {
      event.preventDefault();
      event.stopPropagation();
      onClose();
    }
  };
  const listId = `${id}-commands`;
  const optionId = result => `${id}-${result.id}`;

  return <div ref={box} role="dialog" aria-label="Command search" data-cad-command-search=""
    className={cn(WORKSPACE_SURFACE_CLASS, "pointer-events-auto absolute left-1/2 top-full z-10 mt-2 flex w-80 max-w-[calc(100%-1rem)] -translate-x-1/2 flex-col overflow-hidden")}
    // A press inside keeps focus in the text field, the scrollbar's too; the field itself is pressed as a field is.
    onMouseDown={event => { if (event.target !== field.current) event.preventDefault(); }}
    onBlur={event => { if (!event.currentTarget.contains(event.relatedTarget)) onClose(); }}>
    <input ref={field} type="text" role="combobox" aria-label="Search commands" aria-autocomplete="list" aria-expanded={rows.length > 0}
      aria-controls={rows.length ? listId : undefined} aria-activedescendant={row ? optionId(row) : undefined}
      autoComplete="off" spellCheck={false} placeholder="Search commands" value={query}
      className="h-8 w-full min-w-0 shrink-0 border-b border-border bg-transparent px-3 text-xs text-foreground outline-none placeholder:text-muted-foreground"
      onChange={event => { setQuery(event.target.value); setChosen(0); }} onKeyDown={onKeyDown} />
    {rows.length ? <ScrollArea className="max-h-72">
      <div id={listId} role="listbox" aria-label="Commands" className="flex flex-col p-1">
        {rows.map((each, index) => <div key={each.id} id={optionId(each)} role="option" data-index={index} aria-selected={index === at}
          aria-disabled={each.item.disabled || undefined} aria-description={each.item.description}
          className={cn(ROW_CLASS, !each.item.disabled && HOVER_CLASS, index === at && CHOSEN_CLASS)} onClick={() => run(each)}>
          {each.item.icon}
          <span className="min-w-0 truncate">{each.label}</span>
          {each.detail ? <> <span className="shrink-0 text-muted-foreground">{each.detail}</span></> : null}
        </div>)}
      </div>
    </ScrollArea> : <p role="status" className="px-3 py-2 text-xs text-muted-foreground">No command found.</p>}
    {row?.item.disabled && row.item.description ? <p role="status" className="border-t border-border px-3 py-2 text-tiny leading-4 text-muted-foreground">
      {row.item.description}
    </p> : null}
  </div>;
}
