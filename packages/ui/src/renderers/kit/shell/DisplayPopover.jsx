import {
  DropdownMenu, DropdownMenuCheckboxItem, DropdownMenuContent, DropdownMenuLabel, DropdownMenuRadioGroup,
  DropdownMenuRadioItem, DropdownMenuSeparator, DropdownMenuTrigger
} from "@text-to-cad/ui/primitives/dropdown-menu";
import { ToolbarButton } from "@text-to-cad/ui/primitives/toolbar-button";
import { useI18n } from "@text-to-cad/ui/i18n";
import { cn } from "@text-to-cad/ui/utils";
import { FLOATING_SURFACE_CLASS } from "../../../lib/floatingSurface.js";
import { useStripButtonClass } from "../tools/FloatingToolBar.js";
import { GridIcon } from "../view-settings/DisplayModeOptions.js";

/**
 * Display's choices, one list wherever it is shown (the Display tile's menu, a phone's More
 * submenu): the file's modes, then, after a rule, the Grid switch, which every mode draws, and the
 * renderer's own switches on what it draws of the file (`gates`: an FEA result's loads and
 * fixtures, a CAM job's rapids and stock), each with a muted line under its name saying what it
 * draws where it has one (`description`).
 *
 * @param {{ mode: { value: string, options: { value: string, label: string, Icon?: Function }[], onChange(value: string): void },
 *   grid: { value: boolean, onChange(value: boolean): void },
 *   gates?: readonly { id: string, label: string, description?: string, checked: boolean, onChange(value: boolean): void }[] }} props
 */
export function DisplayMenuItems({ mode, grid, gates = [] }) {
  const { t } = useI18n();
  return <>
    <DropdownMenuRadioGroup aria-label={t("display.mode")} value={mode.value} onValueChange={mode.onChange}>
      {mode.options.map(({ value, Icon }) => <DropdownMenuRadioItem key={value} value={value} data-display-mode-option={value}>
        {Icon ? <Icon className="size-4" /> : null}{t(`mode.${value}`)}
      </DropdownMenuRadioItem>)}
    </DropdownMenuRadioGroup>
    <DropdownMenuSeparator />
    {/* Ticking it leaves the menu open, as every checkbox row in a menu does: the grid is seen coming and going. */}
    <DropdownMenuCheckboxItem checked={grid.value} onCheckedChange={value => grid.onChange(value === true)}
      onSelect={event => event.preventDefault()} data-display-grid="">
      <GridIcon className="size-4" />{t("display.grid")}
    </DropdownMenuCheckboxItem>
    {gates.map(gate => <DropdownMenuCheckboxItem key={gate.id} checked={gate.checked} onCheckedChange={value => gate.onChange(value === true)}
      onSelect={event => event.preventDefault()} data-display-gate={gate.id} aria-label={gate.label} aria-description={gate.description || undefined}
      className={gate.description ? "items-start" : undefined}>
      <span className="size-4 shrink-0" aria-hidden="true" />
      <span className="flex min-w-0 flex-col">{gate.label}
        {gate.description ? <span className="text-micro text-muted-foreground" aria-hidden="true">{gate.description}</span> : null}</span>
    </DropdownMenuCheckboxItem>)}
  </>;
}

/**
 * The Display tile: the mode on screen's sphere, opening Display's list (`DisplayMenuItems`). A
 * mode chosen closes it; the Grid switch leaves it open. Projection is a menu of its own
 * (`ProjectionPopover.jsx`); on a phone Display is More's submenu instead (`RendererShell.jsx`).
 */
export default function DisplayPopover({ disabled = false, boundary = null, tooltipSide = "top", onOpenChange, mode, grid, gates = [] }) {
  const { t } = useI18n();
  const tileClass = useStripButtonClass();
  const current = mode.options.find(option => option.value === mode.value) || mode.options[0];
  const Icon = current?.Icon;
  const currentLabel = t(`mode.${current?.value || "solid"}`);
  return <DropdownMenu modal={false} onOpenChange={onOpenChange}>
    <DropdownMenuTrigger asChild>
      <ToolbarButton label={t("display.modeCurrent", { mode: currentLabel })} tooltip={t("display.label")} tooltipSide={tooltipSide} disabled={disabled}
        className={tileClass} data-display-mode={current?.value}>
        {Icon ? <Icon /> : null}
      </ToolbarButton>
    </DropdownMenuTrigger>
    {/* Closes with no exit animation, so a quick second press always reaches the tile. */}
    <DropdownMenuContent align="center" sideOffset={6} collisionPadding={8} collisionBoundary={boundary || undefined} aria-label={t("display.label")}
      className={cn(FLOATING_SURFACE_CLASS, gates.some(gate => gate.description) ? "w-64" : "w-44", "data-[state=closed]:animate-none!")}>
      <DropdownMenuLabel className="text-muted-foreground">{t("display.label")}</DropdownMenuLabel>
      <DisplayMenuItems mode={mode} grid={grid} gates={gates} />
    </DropdownMenuContent>
  </DropdownMenu>;
}
