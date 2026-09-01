import { Pause, Play, RotateCcw } from "lucide-react";
import { cn } from "@/ui/utils";
import {
  ANIMATION_SPEED_MAX,
  ANIMATION_SPEED_MIN,
  REST_CLIP_ID
} from "cadgen-js/common/animationClock";
import { useAnimationClock } from "@/workbench/animationClockStore";
import { animationClipOptions } from "@/workbench/animationClipOptions";
import { Button } from "../ui/button";
import { Slider } from "../ui/slider";
import {
  FILE_SHEET_COMPACT_BUTTON_CLASSES,
  FILE_SHEET_PRECISION_SLIDER_CLASSES,
  FileSheetButtonRow,
  FileSheetSelectRow,
  FileSheetSliderField,
  FileSheetStatusText,
  FileSheetSubsection,
  FileSheetToggleRow,
  parseFileSheetNumberInput
} from "./FileSheet";

// The ANIMATION tab: pick a clip, play it, scrub it.
//
// The other half of the pose/animation split. Clips are choreography compiled
// from the sidecar's copied .anim.js text and are pure functions of t, which is
// why scrub and pause need nothing but a number. This section never reads a
// DOF, a mate or a preset.

const compactButtonClasses = FILE_SHEET_COMPACT_BUTTON_CLASSES;

function formatSeconds(value) {
  const numericValue = Math.max(Number(value) || 0, 0);
  return `${numericValue.toFixed(numericValue >= 10 ? 1 : 2)}s`;
}

function formatSpeed(value) {
  const numericValue = Number(value);
  return `${(Number.isFinite(numericValue) ? numericValue : 1).toFixed(1)}x`;
}

// The time slider tracks the LIVE clock while playing: the elapsed time on the
// runtime snapshot only moves when playback stops, because a playing clip
// publishes through the clock store instead of React state.
function AnimationTimeControl({ playing, elapsedSec, duration, enabled, onScrub }) {
  const liveElapsedSec = useAnimationClock();
  const rawElapsedSec = playing ? liveElapsedSec : elapsedSec;
  const value = Math.min(Math.max(Number(rawElapsedSec) || 0, 0), duration);
  return (
    <FileSheetSliderField
      label="Time"
      value={formatSeconds(value)}
      onValueCommit={(nextValue) => {
        onScrub?.(parseFileSheetNumberInput(nextValue, {
          fallback: value,
          min: 0,
          max: duration
        }));
      }}
      valueInputProps={{
        disabled: !enabled,
        ariaLabel: "Animation time value"
      }}
    >
      <Slider
        className={FILE_SHEET_PRECISION_SLIDER_CLASSES}
        value={[value]}
        min={0}
        max={duration}
        step={0.01}
        onValueChange={(nextValue) => onScrub?.(nextValue?.[0] ?? 0)}
        disabled={!enabled}
        aria-label="Animation time"
      />
    </FileSheetSliderField>
  );
}

export default function AnimationControlsSection({ runtime = null }) {
  const clips = Array.isArray(runtime?.clips) ? runtime.clips : [];
  const status = String(runtime?.status || "").trim();
  const error = String(runtime?.error || "").trim();
  const activeClip = clips.find((clip) => clip.id === runtime?.activeClipId) || null;
  const duration = Math.max(Number(activeClip?.duration) || 1, 0.001);
  // "No clip" is a selection, not a missing one: with no clip active the model
  // shows whatever the Pose tab set and the evaluator never runs.
  const atRest = !activeClip;
  if (!animationControlsHaveContent(runtime)) {
    return null;
  }

  return (
    <div className="py-2">
      {status === "loading" ? (
        <FileSheetStatusText className="py-2">Loading animation...</FileSheetStatusText>
      ) : null}
      {error ? (
        <FileSheetStatusText tone="error" className="py-2">{error}</FileSheetStatusText>
      ) : null}

      {clips.length ? (
        // "Playback", not "Clip": the group and the row inside it must not share
        // a name (viewer/docs/settings-ui.md), and the group is the transport.
        <FileSheetSubsection title="Playback">
          {/* The section's primary control: which clip is selected reframes the
              transport and the time/speed rows beneath it. The built-in "No clip"
              entry is the transport's idle state -- the model stays wherever the
              Pose tab put it -- and sits apart from the authored clips, which are
              grouped under their own heading (see workbench/animationClipOptions). */}
          <FileSheetSelectRow
            stacked
            label="Clip"
            value={activeClip?.id || REST_CLIP_ID}
            onValueChange={(nextValue) => {
              runtime?.onClipSelect?.(nextValue === REST_CLIP_ID ? "" : nextValue);
            }}
            ariaLabel="Animation clip"
            options={animationClipOptions(clips)}
          />
          {/* "Restart" is deliberately not called "Reset": it returns playback to
              zero, where the Pose tab's Reset returns the DOFs to their defaults. */}
          <FileSheetButtonRow columns={2}>
            <Button
              type="button"
              variant="outline"
              size="sm"
              className={cn(compactButtonClasses, "justify-center")}
              onClick={() => runtime?.onPlayToggle?.()}
              aria-label={`${runtime?.playing ? "Pause" : "Play"} animation`}
              title={`${runtime?.playing ? "Pause" : "Play"} animation`}
            >
              {runtime?.playing ? (
                <Pause className="h-3.5 w-3.5" strokeWidth={2} aria-hidden="true" />
              ) : (
                <Play className="h-3.5 w-3.5" strokeWidth={2} aria-hidden="true" />
              )}
              <span>{runtime?.playing ? "Pause" : "Play"}</span>
            </Button>
            <Button
              type="button"
              variant="outline"
              size="sm"
              className={cn(compactButtonClasses, "justify-center")}
              onClick={() => runtime?.onRestart?.()}
              disabled={atRest}
              aria-label="Restart animation"
              title="Restart"
            >
              <RotateCcw className="h-3.5 w-3.5" strokeWidth={2} aria-hidden="true" />
              <span>Restart</span>
            </Button>
          </FileSheetButtonRow>
          <FileSheetToggleRow
            label="Loop"
            checked={runtime?.loopEnabled !== false}
            onCheckedChange={(checked) => runtime?.onLoopToggle?.(checked)}
            disabled={atRest}
            ariaLabel="Loop animation playback"
          />
          <AnimationTimeControl
            playing={runtime?.playing === true}
            elapsedSec={runtime?.elapsedSec}
            duration={duration}
            enabled={!atRest}
            onScrub={runtime?.onScrub}
          />
          <FileSheetSliderField
            label="Speed"
            value={formatSpeed(runtime?.speed)}
            onValueCommit={(nextValue) => {
              runtime?.onSpeedChange?.(parseFileSheetNumberInput(nextValue, {
                fallback: runtime?.speed || 1,
                min: ANIMATION_SPEED_MIN,
                max: ANIMATION_SPEED_MAX
              }));
            }}
            valueInputProps={{
              disabled: atRest,
              ariaLabel: "Animation speed value"
            }}
          >
            <Slider
              className={FILE_SHEET_PRECISION_SLIDER_CLASSES}
              value={[Number(runtime?.speed) || 1]}
              min={ANIMATION_SPEED_MIN}
              max={ANIMATION_SPEED_MAX}
              step={0.1}
              onValueChange={(nextValue) => runtime?.onSpeedChange?.(nextValue?.[0] ?? 1)}
              disabled={atRest}
              aria-label="Animation speed"
            />
          </FileSheetSliderField>
        </FileSheetSubsection>
      ) : null}
    </div>
  );
}

export function animationControlsHaveContent(runtime) {
  const clips = Array.isArray(runtime?.clips) ? runtime.clips : [];
  const status = String(runtime?.status || "").trim();
  const error = String(runtime?.error || "").trim();
  return Boolean(clips.length || status === "loading" || error);
}

export function buildAnimationControlsTab(props = {}) {
  if (!animationControlsHaveContent(props.runtime)) {
    return null;
  }
  return {
    id: props.value || "animation",
    title: props.title || "Animation",
    content: <AnimationControlsSection {...props} />
  };
}
