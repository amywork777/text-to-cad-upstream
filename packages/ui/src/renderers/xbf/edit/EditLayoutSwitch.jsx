import { PencilRuler } from "lucide-react";
import { DropdownMenuRadioGroup, DropdownMenuRadioItem } from "@text-to-cad/ui/primitives/dropdown-menu";
import { TooltipHint } from "@text-to-cad/ui/primitives/tooltip";
import { cn } from "@text-to-cad/ui/utils";

const OPTIONS = Object.freeze([
  { value: "ai", label: "AI", hint: "Select on the model and ask the agent to change it" },
  { value: "manual", label: "CAD", hint: "Model the part yourself: sketches, features and their sizes" },
]);

/**
 * The switch between the two ways to change a part (`editLayout.js`): CAD, edit mode laid out as a
 * CAD tool, and AI, the viewer as it is, where a selection goes to the agent. It is the first of the
 * view's own controls (`editLayoutControl`): at the strip's end before Projection, or at the
 * toolbar's tab row's right end while CAD is up. Held while a command or a sketch is open: it is
 * finished or cancelled first.
 *
 * @param {{ value: "manual" | "ai", onChange: (value: "manual" | "ai") => void, disabled?: boolean }} props
 */
export default function EditLayoutSwitch({ value, onChange, disabled = false }) {
  // A segmented control: the way in use raised out of its track, so which one is on is plain.
  return <div role="radiogroup" aria-label="Editing" data-cad-edit-layout=""
    className="mr-1 flex h-6 shrink-0 items-center gap-0.5 rounded-md bg-muted p-0.5">
    {OPTIONS.map(option => {
      const chosen = value === option.value;
      return <TooltipHint key={option.value} content={option.hint}>
        <button type="button" role="radio" aria-checked={chosen} disabled={disabled && !chosen}
          className={cn("flex h-5 items-center rounded px-2 text-tiny leading-none text-muted-foreground transition-colors hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/45 disabled:pointer-events-none disabled:opacity-40",
            chosen && "bg-background text-foreground shadow-sm ring-1 ring-border")}
          onClick={() => { if (!chosen) onChange(option.value); }}>{option.label}</button>
      </TooltipHint>;
    })}
  </div>;
}

/**
 * The switch as one of the view's own controls (`RendererShell`'s `layoutControl`, a
 * `ViewportViewControl`): its tile, and on a phone a row of More whose submenu is the two ways.
 *
 * @param {{ value: "manual" | "ai", onChange: (value: "manual" | "ai") => void, disabled?: boolean }} props
 */
export function editLayoutControl({ value, onChange, disabled = false }) {
  return {
    id: "edit-layout", label: "Editing", icon: <PencilRuler aria-hidden="true" />,
    tile: <EditLayoutSwitch value={value} onChange={onChange} disabled={disabled} />,
    submenu: () => <DropdownMenuRadioGroup value={value} onValueChange={next => { if (next !== value) onChange(next); }}>
      {OPTIONS.map(option => <DropdownMenuRadioItem key={option.value} value={option.value} disabled={disabled && option.value !== value}>
        {option.label}</DropdownMenuRadioItem>)}
    </DropdownMenuRadioGroup>,
  };
}
