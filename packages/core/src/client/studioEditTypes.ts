// Studio's edit mode, its types (studio-base, not Jake's text-to-cad): what `studioEdit.js` sends and
// reads over `/api/v1/local/edit/*`. `CadClient` (`types.ts`) extends `CadStudioEdit`.
import type { CadRequestOptions } from './types.js';

/** A number in a part's source, as edit mode shows it: a named size, or a feature's input. */
export interface CadEditValue {
  label?: string;
  name?: string | null;
  value: number;
  display?: string;
  text?: string;
  unit?: string;
  formula?: string;
  leaves?: string[];
  length?: boolean;
  id?: string;
  file?: string;
  line?: number;
}

/** A dimension of a feature, drawn on the model in its own millimetres. */
export interface CadEditDimension {
  id: string;
  name: string;
  label: string;
  display: string;
  formula: string;
  leaves: string[];
  row: string | null;
  anchor: [number, number, number];
  lines: [number, number, number][][];
}

/** One feature of a part's history: an operation of its script, at the line that asked for it. */
export interface CadEditRow {
  key: string;
  name: string | null;
  kind: string;
  code?: string;
  file?: string;
  line?: number;
  count?: number;
  inputs: CadEditValue[];
}

/**
 * One feature of the design tree (`cad/edit/tracer.py`): the rows of the history it stands for (`rows`, in the history's
 * order: the lines of a profile drawn for it, its own, then the rows folded into it), at the statement that makes it, from
 * its first line (`line`, as `text` reads it) to its last (`end`, where the engine read the statement whole). The viewer
 * reads the rest of it as it finds it (`xbf/edit/editMode.js`'s `featureTree`).
 */
export interface CadEditFeature {
  key: string;
  kind: string;
  name: string | null;
  file?: string;
  line?: number;
  end?: number;
  text?: string;
  rows?: string[];
  [field: string]: unknown;
}

export interface CadEditState {
  ok: boolean;
  unchanged?: boolean;
  /** A probe's answer: whether the file has a part script to edit. */
  editable?: boolean;
  reason?: 'no-script';
  error?: string;
  /**
   * Where a part's script stopped (`ok: false`): the frames of the error's traceback that lie in the
   * project's own files, the deepest first and at most six, each named as a row of `rows` names its
   * place, with the line as written. The deepest is the line that raised; when that is in a helper, the
   * next is the call the feature's row stands at. Null when no frame is the project's (a script that does
   * not parse).
   */
  failure?: { frames: { file: string; line: number; text: string }[] } | null;
  script?: string;
  /** Where the part's project starts, as an absolute path: what `files` and each row's `file` are named from. */
  root?: string;
  name?: string;
  units?: 'mm' | 'in';
  files?: Record<string, string>;
  params?: (CadEditValue & { id: string; name: string; text: string })[];
  rows?: CadEditRow[];
  /** A part's design tree; an assembly's is each of its components'. */
  features?: CadEditFeature[];
  /**
   * Which feature made each face (`cad/edit/face_features.py`): a face's number on the part, as its selector has it ("12" for
   * `f12`), → the key of the feature that made it. Only the faces the engine knows; `{}` for an assembly.
   */
  faceFeatures?: Record<string, string>;
  /** How many faces the part read has, for a view to check the faces on screen are that part's before naming one by `faceFeatures`. */
  faceCount?: number;
  /**
   * Who made each feature (`cad/edit/authors.py`), by its key: "you" when a hand edit wrote the first line of its
   * statement, "agent" when a turn's checkpoint holds it. A feature from before Studio kept track, or one a turn still
   * running made, has no entry. An unchanged read says it again, as it moves on when a turn ends.
   */
  authors?: Record<string, 'you' | 'agent'>;
  dimensions?: CadEditDimension[];
  choose?: { id: string; name: string; file: string; line: number }[];
  change?: { literal: string; name: string; file: string; line: number; from: string; to: string };
  building?: { scripts: string[]; done: number; error: string | null };
  /** A preview's answer: what the command would add and take away, or why it cannot be made. */
  preview?: { added?: CadEditPreviewSolid | null; removed?: CadEditPreviewSolid | null; error?: string | null };
}

/**
 * A solid a preview draws over the model, in the part's millimetres: three numbers a corner
 * (`positions`), three corners a triangle (`triangles`), and each edge as the points along it.
 */
export interface CadEditPreviewSolid {
  positions: number[];
  triangles: number[];
  edges: number[][];
}

export interface CadEditChangeRequest {
  file: string;
  files?: Record<string, string>;
  text?: string;
  literal?: string;
  dimension?: string;
  input?: { row: string; index: number };
  leaf?: string;
  /** A modeling command's line (`cad/edit/commands.py`), or lines put back by Undo and Redo. */
  command?: Record<string, unknown>;
  /** A modeling command made without writing it, for its panel to draw what OK would make. */
  preview?: Record<string, unknown>;
  splice?: { file: string; hunks: unknown[] };
  /** A sketch mode change (`cad/edit/sketching.py`): the sketch's file and line, and what to do to it. */
  sketch?: { file?: string; line?: number; name?: string; op: Record<string, unknown> };
  /** Delete on a feature of the design tree (`cad/edit/deleting.py`), by its key and its title. */
  remove?: { feature: string; title?: string };
  /** Suppress (`on`) or Unsuppress on a feature of the design tree (`cad/edit/deleting.py`). */
  suppress?: { feature: string; title?: string; on: boolean };
  /** Where the rollback bar is for this change (alone, the change only moves it), and where it goes once made. */
  bar?: CadEditBar | null;
  bar_after?: CadEditBar | null;
}

/**
 * The face a feature is asked for (`/api/v1/local/edit/face`): `file`, the document on screen (a model's id
 * or a file's path, as `editState` takes it); `face`, its number on the part or an engine ref to it
 * (`plate/face 12`); `files`, the hashes the page read the part from (`editState`'s), so a face of a
 * part that changed since names no feature.
 */
export interface CadEditFaceRequest {
  file: string;
  face: number | string;
  files?: Record<string, string> | null;
}

/**
 * The feature that made a face: `feature`, a key of the read's `features` (or of a component's), or
 * null; `source`, how it was found (`made_by`, the engine's record of the call; `geometric`, the trace's
 * map, for a file); `stale` while the part is being built again or its files moved on, when it names none.
 */
export interface CadEditFaceReply {
  ok: boolean;
  error?: string;
  reason?: string;
  faceFeature?: {
    face: number | string;
    feature: string | null;
    component: string | null;
    source: 'made_by' | 'geometric' | null;
    madeBy: Record<string, unknown> | null;
    stale?: boolean;
  };
}

/** The rollback bar: above the tree item whose first line is `before` (`<file>:<line>`). */
export interface CadEditBar {
  before: string;
}

/** The edit-mode methods a client has (`studioEdit.js`). */
export interface CadStudioEdit {
  /**
   * Edit mode: the part script behind `file` (the script beside a STEP) read as a design. `files`
   * is the hashes the page read last; when none changed the answer is `{ ok: true, unchanged: true }`.
   */
  editState(file: string, files?: Record<string, string> | null, options?: CadRequestOptions & { probe?: boolean; bar?: CadEditBar | null }): Promise<CadEditState>;
  /** Edit mode: one number of the part's source changed, then the parts that use it built again. */
  editChange(change: CadEditChangeRequest, options?: CadRequestOptions): Promise<CadEditState>;
  /** Edit mode: the feature of the design tree that made a face of the document on screen. */
  editFace(request: CadEditFaceRequest, options?: CadRequestOptions): Promise<CadEditFaceReply>;
}
