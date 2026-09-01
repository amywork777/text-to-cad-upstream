import { REST_CLIP_ID } from "cadgen-js/common/animationClock.js";

// The Animation tab's Clip picker.
//
// The transport has one built-in selection -- no clip -- and then the model's
// authored clips. The built-in entry is a STATE of the transport, not a clip:
// with it selected the evaluator never runs and the model sits wherever the
// Pose tab put it. It used to be listed as "Rest" beside the clips, which read
// as an authored clip named Rest, and a pose preset literally named `rest`
// (common in robot sidecars) made two identically labelled entries in two tabs
// that meant different things. So the entry is labelled for what it does to
// the transport ("No clip"), and the authored clips sit under their own group
// heading so the two kinds cannot be read as one list. Poses never synthesise
// clips; nothing here changes which clip plays.
export const NO_CLIP_OPTION_LABEL = "No clip";
export const AUTHORED_CLIPS_GROUP_LABEL = "Clips";

export function animationClipOptions(clips) {
  const authored = Array.isArray(clips) ? clips : [];
  return [
    { value: REST_CLIP_ID, label: NO_CLIP_OPTION_LABEL },
    ...authored.map((clip) => ({
      value: clip.id,
      label: clip.label,
      group: AUTHORED_CLIPS_GROUP_LABEL
    }))
  ];
}
