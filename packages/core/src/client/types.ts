export type CadJson = null | boolean | number | string | CadJson[] | { [key: string]: CadJson };
export interface CadEntry {
  /** The document's id (`cadgen.engine.ids`): rows join by it, so one file is one row however its path is spelled. */
  id?: string;
  /** The file's absolute path, `/`-separated; a document known by its id alone (a model's): its id. */
  file: string;
  /** The document's name where its file does not give it (a model's function). */
  name?: string;
  /** The file to browse from; null for a document with no file of its own (a model's). */
  sourcePath?: string | null;
  kind?: string;
  format?: string;
  sourceFormat?: string;
  renderFormat?: string;
  url?: string;
  hash?: string;
  bytes?: number;
  [key: string]: unknown;
}
export interface CadServerInfo {
  autoReload?: boolean;
  identityToken?: string;
  /** The folder of the most recent launch (`cadgen viewer`), which a launch's relative files are read from. */
  start?: string;
  /** Whether this computer has a file chooser for the home's Open. */
  pick?: boolean;
  /** `darwin`, `win32` or `linux`: which file manager Reveal opens. */
  platform?: string;
  /** The person's home folder, `/`-separated: where the explorer starts with nowhere else to. */
  home?: string;
  /** The engine process answering (`os.getpid()`): another pid after the engine was gone is a new engine, which reloads the page. */
  pid?: number;
  [key: string]: unknown;
}
/** A model in the library every CAD view shares (`GET /__cad/recents`): times in seconds. */
export interface CadRecent {
  path: string; name: string; folder: string;
  /** Identity namespace: the script folder in 0.8; a file’s folder for an opened file. */
  namespace?: string;
  /** When a page last opened it; null for a model no page has opened. */
  opened: number | null;
  /** When it last changed: a file's time on disk (null once it is gone), a model's run. */
  updated: number | null;
  /** When its record was first made: a model's first run, a file's first open; null for a record from before the engine kept it. */
  created: number | null;
  pinned: boolean; missing: boolean;
  /** The picture's name, for `thumbnail()`, and when it was taken. */
  thumbnail: string | null; pictured: number | null;
  /** A CAD file on disk, or a document built from code: a model's, or a shape a program handed over. */
  kind: 'file' | 'model' | 'shape';
  /** A model's or a shape's: the script it was built from (a shape's home). */
  script?: string;
}
/** Whether the person's usage stats are sent (`/__cad/analytics`; nothing asks): `reason` says who decided. */
export interface CadConsent { sharing: boolean; reason: 'default' | 'untold' | 'choice' | 'environment' | 'unavailable'; policy: string; saved?: boolean }
/** A newer text-to-cad, as cadgen's version check says it (`/__cad/version`). */
export interface CadUpdateNotice { latest: string; version: string; text: string; prompt: string; instructions: string }
export interface CadCatalog {
  entries: CadEntry[];
  /** Why an id asked for has no row: the engine holds no such document (its words name the command that builds it again). */
  missing?: string;
  [key: string]: unknown;
}
/** One folder's subfolders and CAD files (`GET /__cad/folder`). */
export interface CadFolder { path: string; entries: { name: string; kind: 'directory' | 'file' }[]; truncated: boolean }
/** The CAD files nested under a folder whose path below it holds the query (`GET /__cad/search`). */
export interface CadSearch { path: string; results: string[]; truncated: boolean }
export interface CadCatalogSnapshot {
  entries: CadEntry[];
  revision: number;
  hydrated: boolean;
  refreshing: boolean;
  error: string;
  /** The last read failed because the engine is gone (`isEngineGone`); cleared by the next that answers. */
  engineGone: boolean;
  /** Of an engine gone, whether one answered and refused the page's token (`isEngineRefused`). */
  engineRefused: boolean;
  /** The server's digest of the last catalog applied ('' before one is): what a change watcher compares. */
  catalogRevision: string;
}
export interface CadRequestOptions { signal?: AbortSignal }
/**
 * What `GET /__cad/drawing` answers: a drawing's modelspace, flattened to the
 * five primitive shapes ezdxf reduces every entity to and its text, placed, in
 * DXF coordinates with y UP. `color: null` is the default pen, painted with the
 * theme's foreground; `bounds: null` is a drawing with nothing in it. See
 * `apps/web/docs/backend.md`.
 */
export interface CadDrawingPayload {
  schemaVersion: number;
  units: { insunits: number; name: string; toMillimetres: number };
  bounds: [number, number, number, number] | null;
  layers: { name: string; color: string | null; entities: number }[];
  entities: { handle: string; type: string; layer: string; block?: string; center?: number[]; radius?: number }[];
  /** The faces `text` primitives are set in, which a `text` names by index. */
  fonts: { family: string; weight: number; italic: boolean }[];
  primitives: ({
    type: 'point' | 'lines' | 'path' | 'filled-paths' | 'filled-polygon';
    entity: string;
    layer: string;
    color: string | null;
    geometry: unknown;
  } | {
    type: 'text';
    entity: string;
    layer: string;
    color: string | null;
    text: string;
    font: number;
    /** Cap height, and the advance width the server measured, in the string's own units. */
    height: number;
    width: number;
    /** `[a, b, c, d, e, f]`: the string's space (baseline-left at the origin, y up) to the drawing's. */
    transform: [number, number, number, number, number, number];
  })[];
  [key: string]: unknown;
}
/**
 * What `GET /__cad/plot` answers: a KiCad board drawn from its file, as geometry per layer
 * (`@text-to-cad/core` `docs/plot-payload.md`). One sheet in millimetres, y DOWN, its top-left
 * corner the origin, drawn on its `background`; its `layers` back to front, each a list of
 * items. `kind` names what it draws, for wording only.
 */
export interface CadPlotPayload {
  schemaVersion: number;
  kind: string;
  /** What wrote the file (`"pcbnew 10.99"`), for wording only. */
  generator?: string;
  /** The board's connections still to make, each drawn as a ratsnest line. */
  unrouted: number | null;
  sheets: { name: string; width: number; height: number; background: string; layers: { id: string; kind: string; side: string; items: Record<string, unknown>[] }[] }[];
  /** The board's index, in sheet millimetres: what the board view's tools point with. */
  board?: Record<string, unknown>;
}
/**
 * What `GET /__cad/xbf` answers: the engine serving a cadgen engine document (`engine`, its origin),
 * the document's id there (`doc`) and its API URL (`url`, `<engine>/api/doc/<doc>`).
 */
/**
 * Where a page reads a document the cadgen engine serves (an `.xbf`, a STEP): its id, its API URL
 * through the viewer (`/__cad/api/doc/<id>`, on the client's origin), and the fetch every read
 * of it is made with (the client's own: the CAD app's travels over its tunnel).
 */
export interface CadEngineDocument {
  doc: string;
  url: string;
  fetch: typeof fetch;
}
/**
 * What `GET /__cad/robot` answers: a URDF, SDF or SRDF resolved by cadgen into the articulation
 * the page plays (`common/articulation.js`), the visuals it draws (each at its rest placement,
 * with its colour and the URL of the mesh it draws), and what the description says about its
 * links and joints, as written. See `packages/cadgen/src/cadgen/robot_payload.py`.
 */
export interface CadRobotPayload {
  schemaVersion: number;
  kind: 'urdf' | 'sdf' | 'srdf';
  name: string;
  root: string;
  articulation: Record<string, unknown>;
  links: { name: string; placement: number[]; visuals: unknown[]; collisions: unknown[]; inertial: unknown }[];
  joints: Record<string, unknown>[];
  visuals: { id: string; link: string; label: string; placement: number[]; color: string; mesh: { format: string; url: string } }[];
  srdf: Record<string, unknown> | null;
  sdf: Record<string, unknown> | null;
  [key: string]: unknown;
}
/** Byte tickets own their buffer exclusively: workers may detach it. URL tickets are approved by the provider. */
export type CadWorkerResourceTicket =
  | { kind: 'url'; url: string; headers?: Record<string, string>; cache?: RequestCache; maxBytes?: number }
  | { kind: 'bytes'; bytes: ArrayBuffer };
export interface CadResourceReadOptions extends CadRequestOptions { maxBytes?: number }
export interface CadResourceProvider {
  /** Main-thread lifetime of the current resource generation; issued worker requests observe it too. */
  readonly signal?: AbortSignal;
  /** Stable within one immutable authorization/generation scope; change it when that scope changes. */
  cacheKey?(url: string): string;
  readJson(url: string, options?: CadRequestOptions): Promise<unknown>;
  readBytes(url: string, options?: CadResourceReadOptions): Promise<ArrayBuffer>;
  byteLength(url: string, options?: CadRequestOptions): Promise<number | null>;
  resolveDependency(source: string, reference: string): string;
  workerTicket(url: string, options?: CadResourceReadOptions): Promise<CadWorkerResourceTicket>;
}
export interface CadRenderSession {
  resources: CadResourceProvider;
  signal: AbortSignal;
  dispose(): void;
}
/** One build of a model: the file a kernel wrote, and whether it is the one on screen. */
export interface CadKernelVariant {
  kernel: string;
  file: string;
  current: boolean;
}
/** Domain service consumed by renderers; HTTP metadata stays on its adapter. */
export interface CadWorkspaceService {
  exports?: ExportService;
  getSnapshot(): CadCatalogSnapshot;
  subscribe(listener: () => void): () => void;
  refresh(options?: CadRequestOptions & {file?: string;markRefreshing?: boolean}): Promise<CadCatalog>;
  /** The row of a document, by its absolute path or its id, read when the catalog has none yet. */
  resolveEntry(path: string, options?: CadRequestOptions): Promise<CadEntry>;
  /** The row the catalog has of a document (its path, or its id), joined by the document's id; null when it has none. */
  entryOf?(path: string): CadEntry | null;
  serverInfo(options?: CadRequestOptions & { fresh?: boolean }): Promise<CadServerInfo>;
  folder(path: string, options?: CadRequestOptions): Promise<CadFolder>;
  search(path: string, query: string, options?: CadRequestOptions): Promise<CadSearch>;
  /**
   * The model a file belongs to, built on other CAD kernels and saved beside it: its own file
   * (kernel `brep`) first, then each kernel's, by kernel name. Empty when it has none. Optional:
   * a client without it offers no kernel menu.
   */
  kernelVariants?(file: string, options?: CadRequestOptions): Promise<CadKernelVariant[]>;
  /** The home's library, newest first. */
  recents(options?: CadRequestOptions): Promise<CadRecent[]>;
  /**
   * A change to the library (`open`, `pin`, `unpin`, `thumbnail`; `remove` a file's entry, its file
   * untouched; `delete` a model, its entry and the engine's copy): the library as it now is.
   */
  changeRecents(change: { action: 'open' | 'pin' | 'unpin' | 'remove' | 'delete' | 'thumbnail'; path: string; png?: string }): Promise<CadRecent[]>;
  /** Keep a model's picture in the library. */
  keepThumbnail(png: Blob, path: string): Promise<CadRecent[]>;
  /** A library picture, by the name the library gives it, as a data URL; null when there is none. */
  thumbnail(name: string, options?: CadRequestOptions): Promise<string | null>;
  /** Open: the model the person picks with the desktop's chooser, by its absolute path, or null. */
  pick(): Promise<string | null>;
  /** Show a file, by its absolute path, in the desktop's file manager. */
  reveal(path: string): Promise<void>;
  /** Whether the person's usage stats are sent; with `share`, their answer (the app menu's toggle). */
  consent(share?: boolean): Promise<CadConsent>;
  /** The language the person chose for every CAD view, or null (Automatic); with `locale`, their choice (null clears it). */
  language(locale?: string | null): Promise<{ locale: string | null }>;
  /** Whether a newer text-to-cad is out: the update button's notice, or null. */
  version(): Promise<{ notice: CadUpdateNotice | null }>;
  /**
   * What the page did -- a person touched it, sent a Quick Edit, used its controls, or the page crashed (`crashOf`) --
   * noted by the server and sent only with consent. Never fails.
   */
  reportActivity(activity: CadActivity): void;
  /** A `.dxf` flattened to 2D render primitives on the server; the client never parses DXF. */
  drawing(file: string, options?: CadRequestOptions): Promise<CadDrawingPayload>;
  /** A KiCad board drawn from its file on the server: geometry per layer, and the board's index. */
  plotPayload(file: string, options?: CadRequestOptions): Promise<CadPlotPayload>;
  /** `GET /__cad/robot`: a robot description resolved for the page (`cadgen.robot_payload`). */
  robot(file: string, options?: CadRequestOptions): Promise<CadRobotPayload>;
  /**
   * `GET /__cad/xbf`: where the page reads a document the cadgen engine serves (an `.xbf`, a STEP),
   * through this server (`lib/xbf/xbfDocument.js`), once the engine holds it. A host without an
   * engine leaves it out, and the xbf renderer says it cannot open the file.
   */
  /** `onProgress` hears each frame of the engine's import of the file while it reads it (a STEP's), as the build frames are shaped. */
  engineDocument?(file: string, options?: CadRequestOptions & { onProgress?(frame: Record<string, unknown>): void }): Promise<CadEngineDocument>;
  /** Whether the engine holds a read of the document now (`GET /__cad/xbf?held=1`), asked without starting one. */
  engineHolds?(file: string, options?: CadRequestOptions): Promise<boolean>;
  readonly resources: CadResourceProvider;
  createRenderSession(options?: { file?: string }): CadRenderSession;
  dispose(): void;
}
/** Reusable HTTP implementation, also used by existing catalog adapters. */
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
 * One feature of the design tree (`cadgen/edit/tracer.py`): the rows of the history it stands for (`rows`, in the history's
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
   * Which feature made each face (`cadgen/edit/face_features.py`): a face's number on the part, as its selector has it ("12" for
   * `f12`), → the key of the feature that made it. Only the faces the engine knows; `{}` for an assembly.
   */
  faceFeatures?: Record<string, string>;
  /** How many faces the part read has, for a view to check the faces on screen are that part's before naming one by `faceFeatures`. */
  faceCount?: number;
  /**
   * Who made each feature (`cadgen/edit/authors.py`), by its key: "you" when a hand edit wrote the first line of its
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
  /** A modeling command's line (`cadgen/edit/commands.py`), or lines put back by Undo and Redo. */
  command?: Record<string, unknown>;
  /** A modeling command made without writing it, for its panel to draw what OK would make. */
  preview?: Record<string, unknown>;
  splice?: { file: string; hunks: unknown[] };
  /** A sketch mode change (`cadgen/edit/sketching.py`): the sketch's file and line, and what to do to it. */
  sketch?: { file?: string; line?: number; name?: string; op: Record<string, unknown> };
  /** Delete on a feature of the design tree (`cadgen/edit/deleting.py`), by its key and its title. */
  remove?: { feature: string; title?: string };
  /** Suppress (`on`) or Unsuppress on a feature of the design tree (`cadgen/edit/deleting.py`). */
  suppress?: { feature: string; title?: string; on: boolean };
  /** Where the rollback bar is for this change (alone, the change only moves it), and where it goes once made. */
  bar?: CadEditBar | null;
  bar_after?: CadEditBar | null;
}

/**
 * The face a feature is asked for (`/__cad/edit/face`): `file`, the document on screen (a model's id
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

export interface CadClient extends CadWorkspaceService {
  readonly origin: string;
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
export interface CadClientOptions {
  resources?: CadResourceProvider;
  origin?: string;
  fetch?: typeof globalThis.fetch;
  pollIntervalMs?: number;
  /** Host visibility policy, evaluated at each polling interval. */
  shouldPoll?: () => boolean;
}

/** A page's crash, as telemetry takes one (`crashOf`): never its message, a value or a URL. */
export interface CadPageCrash {
  where: 'page';
  /** The error's name, such as `TypeError`; `<?>` for one that is no plain name. */
  type: string;
  /** Whether the page went on: an error a view's boundary caught, not one that stopped it. */
  handled: boolean;
  /** Its innermost frames, oldest first: a script file's own name (or `<?>`), a function, a place, and for
   * one of the page's own chunks its debug id, by which PostHog finds the chunk's source map. */
  frames: { file: string; function: string; line: number; column: number; chunk_id?: string }[];
}

/** What `reportActivity` tells the page's server. */
export interface CadActivity {
  touched?: boolean;
  quickEdit?: boolean;
  /** The view's controls a person used since the last report (`@text-to-cad/ui`'s `usage/controls.js`). */
  controls?: { control: string; count: number; seconds: number }[];
  crash?: CadPageCrash;
}

export type ExportFormat = 'step' | 'glb' | 'stl' | 'threemf' | 'dxf' | 'xbf' | 'original';
export interface ExportSource { doc: string; revision: string }
/** One export: `epoch` is the session's (`ExportService.epoch`), `''` until the page has asked it. */
export interface ExportRequest { requestId: string; epoch: string; source: ExportSource; format: ExportFormat }
export interface ExportJob {
  id: string; requestId: string; epoch: string; filename: string;
  state: 'queued' | 'running' | 'cancelling' | 'cancelled' | 'failed' | 'ready' | 'expired';
  stage: string; sequence: number; createdAt: number; finishedAt: number; expiresAt: number;
  bytes?: number; error?: string;
  /** Expired because the browser fetched the whole file (it is deleted then), not by its window. */
  fetched?: boolean;
  /** A STEP's PMI, checked in the file as written (none where the format carries none). */
  pmiVerification?: { matched: number; total: number; problems: string[]; sha256: string } | null;
}
export interface ExportService {
  /** The session's epoch, which a request names so that a server restarted since refuses it. */
  epoch(signal?: AbortSignal): Promise<string>;
  create(request: ExportRequest, signal?: AbortSignal): Promise<ExportJob>;
  status(id: string, sequence?: number, signal?: AbortSignal): Promise<ExportJob>;
  /** Where the browser downloads a ready job's file: the session's own origin, never a token. */
  fileUrl(id: string): string;
}
