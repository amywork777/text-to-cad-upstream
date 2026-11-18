import { useMemo } from "react";
import { useI18n } from "@cad/ui/i18n";
import ToolPanel from "../kit/tools/ToolPanel.jsx";
import { NODE, PORT, layoutGraph, wire } from "./graphLayout.js";

/**
 * The view's panel's Graph tab: the model's names as the graph they make (`cad.omega._graph`, read from the
 * source by the field route), each a block wired from the names its expression uses, inputs (the sliders)
 * at the left and the output at the right, as an nTop notebook's blocks take their inputs from earlier ones.
 * It is a reading of the program, never a second source: the code stays the model, and a block names the
 * line it is written on. A call that returns several values shows each output as a port of its own, wired
 * from the one each name uses; a property read or set on a value (`solid.dp`, `bracket.color = col;`) is a
 * small node off the value it is of.
 */
export default function GraphSection({ graph }) {
  const { t } = useI18n();
  const laid = useMemo(() => layoutGraph(graph), [graph]);
  const byId = new Map(laid.nodes.map(node => [node.id, node]));
  return <ToolPanel id="graph" title={t("field.graph.title")} label={t("field.graph.label")} fit="details">
    <div className="overflow-auto p-2" data-field-graph="">
      <svg width={laid.width + 2} height={laid.height + 2} viewBox={`-1 -1 ${laid.width + 2} ${laid.height + 2}`} role="img"
        aria-label={t("field.graph.label")} className="block text-foreground">
        {laid.edges.map(([from, to, port]) => <path key={`${from}>${to}>${port ?? ""}`} d={wire(byId.get(from), byId.get(to), port)}
          fill="none" className="stroke-muted-foreground/60" strokeWidth={1.25} data-graph-edge={`${from}>${to}`}
          data-graph-port={port ?? undefined} />)}
        {laid.nodes.map(node => <g key={node.id} transform={`translate(${node.x} ${node.y})`} data-graph-node={node.id}
          data-graph-kind={node.kind}>
          <title>{t("field.graph.node", { name: node.id, op: node.op, line: node.line })}</title>
          {node.kind === "property" ? <PropertyNode node={node} /> : node.outputs?.length > 1 ? <OutputsNode node={node} />
            : <>
              <rect width={NODE.width} height={NODE.height} rx={6} strokeWidth={node.kind === "output" ? 1.5 : 1}
                className={node.kind === "input" ? "fill-info/10 stroke-info" : node.kind === "output" ? "fill-background stroke-foreground"
                  : "fill-muted stroke-border"} />
              <text x={8} y={14} className="fill-foreground text-[11px] font-medium">{clip(node.id, 16)}</text>
              <text x={8} y={27} className="fill-muted-foreground text-[10px]">{clip(node.kind === "input" && node.range
                ? `${node.range[0] ?? ""} to ${node.range[1] ?? ""}` : node.op, 19)}</text>
            </>}
        </g>)}
      </svg>
    </div>
  </ToolPanel>;
}

// A call with several outputs: its call's name, then each output's name beside the port it leaves by.
function OutputsNode({ node }) {
  return <>
    <rect width={NODE.width} height={node.height} rx={6} className="fill-muted stroke-border" strokeWidth={1} />
    <text x={8} y={14} className="fill-muted-foreground text-[10px]">{clip(node.op, 19)}</text>
    {node.outputs.map((name, index) => {
      const y = PORT.header + index * PORT.row + PORT.row / 2;
      return <g key={name} data-graph-port={name}>
        <text x={NODE.width - 9} y={y + 3.5} textAnchor="end" className="fill-foreground text-[11px] font-medium">{clip(name, 15)}</text>
        <circle cx={NODE.width} cy={y} r={3} className="fill-background stroke-muted-foreground" strokeWidth={1} />
      </g>;
    })}
  </>;
}

// A property of a value, read (`solid.dp`) or set (`bracket.color =`, dashed): a small node off it.
function PropertyNode({ node }) {
  return <>
    <rect width={NODE.width} height={node.height} rx={node.height / 2} strokeWidth={1} strokeDasharray={node.set ? "3 2" : undefined}
      className="fill-background stroke-border" />
    <text x={10} y={node.height / 2 + 3.5} className="fill-muted-foreground text-[10px]">
      {clip(node.of, 10)}<tspan className="fill-foreground font-medium">{clip(`.${node.op}${node.set ? " =" : ""}`, 12)}</tspan>
    </text>
  </>;
}

const clip = (text, most) => (String(text).length > most ? `${String(text).slice(0, most - 1)}…` : String(text));
