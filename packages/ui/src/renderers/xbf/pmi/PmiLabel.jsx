import { cn } from "@text-to-cad/ui/utils";
import { PmiGlyph } from "./pmiGlyphs.jsx";

// What a PMI callout says, drawn as a drawing draws it, at the UI's own size: a dimension's
// nominal (a diameter's struck circle before it) and its tolerance, stacked where it differs each
// way; a datum's letter in its box; a feature control frame's cells -- its characteristic, its
// value (a diameter zone's struck circle first) and the datums it refers to -- each ruled off from
// the next. Ink on paper, so it reads over any part: the theme's foreground on its background.

const BOX = "inline-flex items-stretch rounded-[2px] border bg-background/95 text-tiny leading-4 tabular-nums text-foreground shadow-sm";
const CELL = "flex items-center px-1";
const GLYPH = "size-3 shrink-0";

function Tolerance({ tolerance }) {
  if (!tolerance) return null;
  if (tolerance.symmetric) return <span className="pl-0.5">{tolerance.text}</span>;
  return <span className="ml-0.5 inline-flex flex-col justify-center text-micro leading-[0.7rem]" data-pmi-tolerance="limits">
    <span>{tolerance.upper}</span><span>{tolerance.lower}</span>
  </span>;
}

/** A callout's words in their box: `pmiCallout`'s pieces, the box in its state's colour. */
export default function PmiLabel({ callout, status = "ok", selected = false, hovered = false, moved = false, className }) {
  const border = status === "missing" || status === "invalid" ? "border-red-500 border-dashed" : status === "ambiguous" ? "border-amber-500 border-dashed"
    : selected ? "border-[#2979ff] ring-2 ring-[#2979ff]/35" : hovered ? "border-foreground" : "border-foreground/60";
  const box = cn(BOX, border, moved && "outline-dashed outline-1 outline-offset-2 outline-[#2979ff]", className);
  if (callout.kind === "dimension") {
    return <span className={cn(box, CELL, "gap-px py-px")} data-pmi-callout="dimension">
      {callout.diameter ? <PmiGlyph name="diameter" className={GLYPH} aria-hidden="true" /> : null}
      <span>{callout.nominal}</span>
      <Tolerance tolerance={callout.tolerance} />
    </span>;
  }
  if (callout.kind === "datum") {
    return <span className={cn(box, CELL, "min-w-5 justify-center py-px font-medium")} data-pmi-callout="datum">{callout.letter}</span>;
  }
  if (callout.kind === "frame") {
    return <span className={cn(box, "divide-x divide-current/40")} data-pmi-callout="frame">
      <span className={CELL}><PmiGlyph name={callout.characteristic} className={GLYPH} aria-hidden="true" /></span>
      <span className={cn(CELL, "gap-px")}>
        {callout.diameter ? <PmiGlyph name="diameter" className={GLYPH} aria-hidden="true" /> : null}
        {callout.value}
      </span>
      {callout.datums.map(datum => <span key={datum} className={CELL}>{datum}</span>)}
    </span>;
  }
  return <span className={cn(box, CELL, "gap-1 py-px text-muted-foreground")} data-pmi-callout="unsupported">
    <PmiGlyph name="unsupported" className={GLYPH} aria-hidden="true" />{callout.text}
  </span>;
}
