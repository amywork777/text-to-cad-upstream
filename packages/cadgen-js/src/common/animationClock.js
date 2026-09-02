// The animation TRANSPORT, shared by every client (viewer Animation tab,
// the docs hero, any embed): which clip is active, where the clock
// is, and how fast it runs. Choreography itself lives in the sidecar's copied
// .anim.js text and is compiled by cadgen-js/common/animationRuntime; this module
// owns only the transport around it.
//
// Independence, restated in code: nothing here reads a step-module definition,
// a DOF, or a pose preset. The Pose tab and the Animation tab share a model and
// nothing else.

// The "no clip" selection. Animation is opt-in: until a clip is chosen the
// evaluator never runs and the model shows exactly the pose the Pose tab set,
// so a model that merely SHIPS clips pays nothing for them.
export const REST_CLIP_ID = "__rest__";

export const ANIMATION_SPEED_MIN = 0.1;
export const ANIMATION_SPEED_MAX = 3;

function normalizeString(value) {
  return String(value == null ? "" : value).trim();
}

function clampNumber(value, min, max) {
  const numericValue = Number(value);
  if (!Number.isFinite(numericValue)) {
    return min;
  }
  return Math.min(Math.max(numericValue, min), max);
}

export function clampAnimationSpeed(value) {
  return clampNumber(value, ANIMATION_SPEED_MIN, ANIMATION_SPEED_MAX);
}

export function animationClipDuration(clip) {
  return Math.max(Number(clip?.duration) || 0, 0.001);
}

/** Compiled clips (an id -> clip record map) as an ordered list for the UI. */
export function animationClipList(clips) {
  if (!clips || typeof clips !== "object") {
    return [];
  }
  return Object.values(clips)
    .filter((clip) => clip && typeof clip.update === "function")
    .map((clip) => ({
      id: String(clip.id),
      label: String(clip.label || clip.id),
      duration: animationClipDuration(clip),
      loop: clip.loop !== false
    }));
}

export function hasAnimationClips(clips) {
  return animationClipList(clips).length > 0;
}

/** The clip an id selects, or null for rest / an id no longer in the model. */
export function findAnimationClip(clips, clipId) {
  const id = normalizeString(clipId);
  if (!id || id === REST_CLIP_ID || !clips || typeof clips !== "object") {
    return null;
  }
  const clip = clips[id];
  return clip && typeof clip.update === "function" ? clip : null;
}

/** The id the transport should act on when the user hits Play at rest. */
export function firstAnimationClipId(clips) {
  return animationClipList(clips)[0]?.id || "";
}

/** One frozen frame from a `{clip, time}` request — the snapshot job's
 * `animation` field. The id resolves exactly as the viewer's transport resolves
 * its active clip (findAnimationClip), and the result is the same
 * `{clip, elapsedSec, playing}` the viewer hands its render pass, so a still at
 * time t IS the frame the viewer shows there. An unknown id fails with the
 * declared set — nothing renders a plausible rest frame under a typo. Time
 * passes through unclamped: looping and clamping belong to the evaluator, for
 * stills and playback alike. */
export function resolveAnimationFrame(clips, request) {
  const id = normalizeString(request?.clip);
  if (!id) {
    throw new Error("animation requires a clip name ({clip, time})");
  }
  const clip = findAnimationClip(clips, id);
  if (!clip) {
    const declared = animationClipList(clips).map((entry) => entry.id);
    throw new Error(
      declared.length
        ? `Unknown animation clip: ${id}. This model declares: ${declared.join(", ")}`
        : `Unknown animation clip: ${id}. This model declares no animation clips`
    );
  }
  const rawTime = request?.time;
  const time = rawTime === undefined || rawTime === null ? 0 : Number(rawTime);
  if (!Number.isFinite(time) || time < 0) {
    throw new Error(`animation time must be seconds >= 0, got ${JSON.stringify(rawTime)}`);
  }
  return { clip, elapsedSec: time, playing: false };
}

export function buildDefaultAnimationState() {
  return {
    activeClipId: "",
    playing: false,
    elapsedSec: 0,
    speed: 1,
    loopEnabled: true
  };
}

/** Restore a persisted slice against the clips this model actually has:
 * a clip that no longer exists falls back to rest, and playback never resumes
 * on load (a session restore that starts animating on its own is a surprise). */
export function restoreAnimationState(stored, clips) {
  const defaults = buildDefaultAnimationState();
  if (!stored || typeof stored !== "object") {
    return defaults;
  }
  const clip = findAnimationClip(clips, stored.activeClipId);
  return {
    activeClipId: clip?.id || "",
    playing: false,
    elapsedSec: clip ? clampAnimationElapsed(stored.elapsedSec, animationClipDuration(clip)) : 0,
    speed: clampAnimationSpeed(stored.speed ?? defaults.speed),
    loopEnabled: typeof stored.loopEnabled === "boolean" ? stored.loopEnabled : defaults.loopEnabled
  };
}

export function clampAnimationElapsed(value, duration) {
  return clampNumber(value, 0, Math.max(Number(duration) || 0, 0));
}

/** Advance the clock one tick. Looping wraps; a non-looping clip stops at its
 * end, which is the one place playback ends on its own. */
export function advanceAnimationElapsed({
  elapsedSec = 0,
  deltaSec = 0,
  speed = 1,
  duration = 1,
  loopEnabled = true
} = {}) {
  const safeDuration = Math.max(Number(duration) || 0, 0.001);
  const next = Math.max(Number(elapsedSec) || 0, 0)
    + (Math.max(Number(deltaSec) || 0, 0) * clampAnimationSpeed(speed));
  if (loopEnabled) {
    return { elapsedSec: next % safeDuration, playing: true };
  }
  if (next >= safeDuration) {
    return { elapsedSec: safeDuration, playing: false };
  }
  return { elapsedSec: next, playing: true };
}

export function animationNowMs() {
  if (typeof performance !== "undefined" && typeof performance.now === "function") {
    return performance.now();
  }
  return Date.now();
}

// Frame pacing for playback.  The floor sits under a display frame so an
// unsaturated model publishes on every rAF; the ceiling stops a very heavy
// model from pacing itself below 4 fps.
export const MIN_ANIMATION_FRAME_MS = 8;
export const SATURATED_ANIMATION_FRAME_MS = 32;
export const MAX_ANIMATION_FRAME_MS = 250;

// How long to wait before publishing the next animation frame.
//
// Publishing costs far more than the tick that publishes it -- the store notify
// re-renders the render pane, re-evaluates the clip across every display record
// and redraws the scene.  On a large assembly that lands well over a display
// frame, so publishing on every rAF saturates the main thread: the clock keeps
// advancing but the browser never gets a slot to composite, and playback reads
// as frozen even though scrubbing the same clip still works (a scrub pays the
// cost once).
//
// The cost of a frame is measured as the gap to the following callback, which
// is the one number that includes the downstream render.  While that gap stays
// inside a couple of display frames nothing is overrunning -- rAF is simply
// running at the refresh rate -- so pace at the floor and publish every time.
// Once it climbs past that, frames ARE overrunning, so budget at twice what the
// last one cost: the browser gets roughly half the wall clock back for
// compositing and input, and playback degrades to a lower frame rate instead of
// locking up the tab.
//
// Budgeting at exactly the measured cost would do nothing -- the callback that
// measures a 73 ms frame arrives 73 ms after it, already clearing a 73 ms
// budget -- so the factor is what actually buys the idle time.
export function animationFrameBudgetMs(publishCostMs) {
  const cost = Number(publishCostMs);
  if (!Number.isFinite(cost) || cost <= SATURATED_ANIMATION_FRAME_MS) {
    return MIN_ANIMATION_FRAME_MS;
  }
  return Math.min(cost * 2, MAX_ANIMATION_FRAME_MS);
}

export function shouldPublishAnimationFrame({ timeMs, publishedAtMs, publishCostMs }) {
  if (!Number.isFinite(publishedAtMs)) {
    return true;
  }
  return (timeMs - publishedAtMs) >= animationFrameBudgetMs(publishCostMs);
}
