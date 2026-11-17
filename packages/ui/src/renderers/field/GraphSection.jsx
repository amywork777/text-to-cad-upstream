import { useMemo } from "react";
import { useI18n } from "@cad/ui/i18n";
import ToolPanel from "../kit/tools/ToolPanel.jsx";
import { NODE, layoutGraph, wire } from "./graphLayout.js";

/**
 * The view's panel's Graph tab: the model's names as the graph they make (`cad.omega._graph`, read from the
 * source by the field route), each a block wired from the names its expression uses, inputs (the sliders)
 * at the left and the output at the right, as an nTop notebook's blocks take their inputs from earlier ones.
 * It is a reading of the program, never a second source: the code stays the model, and a block names the
 * line it is written on.
 */
export default function GraphSection({ graph }) {
  const { t } = useI18n();
  const laid = useMemo(() => layoutGraph(graph), [graph]);
  const byId = new Map(laid.nodes.map(node => [node.id, node]));
  return <ToolPanel id="graph" title={t("field.graph.title")} label={t("field.graph.label")} fit="details">
    <div className="overflow-auto p-2" data-field-graph="">
      <svg width={laid.width + 2} height={laid.height + 2} viewBox={`-1 -1 ${laid.width + 2} ${laid.height + 2}`} role="img"
        aria-label={t("field.graph.label")} className="block text-foreground">
        {laid.edges.map(([from, to]) => <path key={`${from}>${to}`} d={wire(byId.get(from), byId.get(to))} fill="none"
          className="stroke-muted-foreground/60" strokeWidth={1.25} />)}
        {laid.nodes.map(node => <g key={node.id} transform={`translate(${node.x} ${node.y})`} data-graph-node={node.id}>
          <title>{`${node.id}: ${node.op}, line ${node.line}`}</title>
          <rect width={NODE.width} height={NODE.height} rx={6} strokeWidth={node.kind === "output" ? 1.5 : 1}
            className={node.kind === "input" ? "fill-info/10 stroke-info" : node.kind === "output" ? "fill-background stroke-foreground"
              : "fill-muted stroke-border"} />
          <text x={8} y={14} className="fill-foreground text-[11px] font-medium">{clip(node.id, 16)}</text>
          <text x={8} y={27} className="fill-muted-foreground text-[10px]">{clip(node.kind === "input" && node.range
            ? `${node.range[0] ?? ""} to ${node.range[1] ?? ""}` : node.op, 19)}</text>
        </g>)}
      </svg>
    </div>
  </ToolPanel>;
}

const clip = (text, most) => (String(text).length > most ? `${String(text).slice(0, most - 1)}…` : String(text));
