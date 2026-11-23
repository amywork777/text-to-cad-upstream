// Studio (studio-base): the view's panel toggle on its strip, where the file viewer draws no navbar to hold it
// (`chrome: "bare"`, Studio's host, whose tab names the file). `ViewFrame.jsx` puts it first among the strip's view
// controls, before Display and Preview, as the navbar puts it first in its row.
import { ToolbarButton } from "@cad/ui/primitives/toolbar-button";
import { SidebarIcon } from "../../../file-viewer/navigation/ViewerNavbar.jsx";
import { useStripButtonClass } from "../tools/FloatingToolBar.js";

/** The toggle as the strip's tile: its 28px, its name and key in its tooltip, its state said by `aria-expanded`. */
function PanelStripTile({ toggle }) {
  return <ToolbarButton label={toggle.label} shortcut={toggle.shortcut || ""} tooltipHidden={toggle.peeking === true}
    aria-expanded={toggle.open} aria-disabled={toggle.disabled || undefined} onClick={toggle.disabled ? undefined : toggle.toggle}
    {...(toggle.hover ?? null)} className={useStripButtonClass()} data-strip-panel="left">
    <SidebarIcon />
  </ToolbarButton>;
}

/**
 * The strip's view controls with the panel's toggle first, where the view has one and no navbar holds it
 * (`navbarShown === false`); the strip's own controls as they are otherwise.
 * @param {readonly object[]} views  The strip's view controls (`FloatingToolBar`'s `views`).
 * @param {{ left?: object | null } | null} toggles  The view's toggle (`file-viewer/panelToggles.js`).
 * @param {boolean | null} navbarShown  `file-viewer/navbarSlots.js`'s `useNavbarShown()`.
 */
export function withStripPanelToggle(views, toggles, navbarShown) {
  const toggle = navbarShown === false ? toggles?.left : null;
  if (!toggle) return views;
  return [{ id: "panel", label: toggle.label, icon: <SidebarIcon />, disabled: toggle.disabled, onSelect: toggle.toggle,
    tile: <PanelStripTile toggle={toggle} /> }, ...views];
}
