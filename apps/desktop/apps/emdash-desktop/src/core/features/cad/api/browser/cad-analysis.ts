import { encodeResourceUri } from '@emdash/core/primitives/path/api';
import { z } from 'zod';
import { getFilesClient } from '@core/features/files/api/browser/client';
import { resolveWorkspacePath } from '@core/features/workspaces/api/browser/workspace-path';
import { hostFileRefFromNativePath } from '@core/primitives/desktop-runtime/api';

const MAX_ANALYSIS_BYTES = 256 * 1024;

export const cadAnalysisTypeSchema = z.enum([
  'static-structural',
  'thermal',
  'modal',
  'flow',
  'other',
]);
export const cadAnalysisStatusSchema = z.enum(['planned', 'running', 'completed', 'failed']);
export const cadAnalysisFileRoleSchema = z.enum(['input', 'mesh', 'result', 'report', 'image']);

const cadAnalysisFileSchema = z
  .object({
    id: z.string().min(1),
    name: z.string().min(1).max(300),
    role: cadAnalysisFileRoleSchema,
    relativePath: z.string().min(1).max(1_000),
    addedAt: z.string(),
  })
  .strict();

export const cadAnalysisManifestSchema = z
  .object({
    version: z.literal(1),
    id: z.string().min(1),
    name: z.string().min(1).max(200),
    type: cadAnalysisTypeSchema,
    status: cadAnalysisStatusSchema,
    model: z
      .object({
        contextKey: z.string().min(1),
        path: z.string().min(1),
        revisionId: z.string().nullable(),
        validatedAt: z.string().nullable(),
      })
      .strict(),
    materialId: z.string().nullable(),
    solver: z.string().max(200),
    objective: z.string().max(2_000),
    loads: z.string().max(4_000),
    constraints: z.string().max(4_000),
    notes: z.string().max(4_000),
    files: z.array(cadAnalysisFileSchema),
    createdAt: z.string(),
    updatedAt: z.string(),
  })
  .strict();

const cadAnalysisIndexSchema = z
  .object({
    version: z.literal(1),
    manifests: z.array(z.string().min(1).max(1_000)),
  })
  .strict();

export type CadAnalysisType = z.infer<typeof cadAnalysisTypeSchema>;
export type CadAnalysisStatus = z.infer<typeof cadAnalysisStatusSchema>;
export type CadAnalysisFileRole = z.infer<typeof cadAnalysisFileRoleSchema>;
export type CadAnalysisManifest = z.infer<typeof cadAnalysisManifestSchema>;

export function cadAnalysisRootPath(modelPath: string): string {
  const normalized = modelPath.replaceAll('\\', '/');
  if (
    normalized.startsWith('/') ||
    /^[a-zA-Z]:\//.test(normalized) ||
    normalized.split('/').includes('..')
  ) {
    throw new Error('CAD analysis paths must stay inside the model workspace.');
  }
  const directory = normalized.includes('/')
    ? normalized.slice(0, normalized.lastIndexOf('/'))
    : '';
  const filename = normalized.split('/').at(-1) ?? 'model';
  const stem = filename
    .replace(/\.(?:step|stp)\.py$/i, '')
    .replace(/\.implicit\.(?:mjs|js)$/i, '')
    .replace(/\.(?:step|stp)$/i, '');
  return [directory, 'analyses', safeSegment(stem, 'model')].filter(Boolean).join('/');
}

export function cadAnalysisFolderPath(modelPath: string, analysisId: string): string {
  return `${cadAnalysisRootPath(modelPath)}/${safeSegment(analysisId, 'analysis')}`;
}

export async function loadCadAnalyses(options: {
  workspacePath: string;
  modelPath: string;
  sshConnectionId?: string;
}): Promise<CadAnalysisManifest[]> {
  const client = await getFilesClient();
  const root = cadAnalysisRootPath(options.modelPath);
  const indexPath = `${root}/index.json`;
  const exists = await client.fs.exists({ uri: analysisUri(options, indexPath) });
  if (!exists.success) throw new Error(fileError(exists.error));
  if (!exists.data.exists) return [];
  const index = cadAnalysisIndexSchema.parse(
    JSON.parse(await readText(client, options, indexPath, 'analysis index'))
  );
  const analyses = await Promise.all(
    index.manifests.map(async (path) => {
      if (!path.startsWith(`${root}/`) || path.split('/').includes('..')) {
        throw new Error('The analysis index contains a manifest outside its model folder.');
      }
      return cadAnalysisManifestSchema.parse(
        JSON.parse(await readText(client, options, path, 'analysis manifest'))
      );
    })
  );
  return analyses.sort((left, right) => right.updatedAt.localeCompare(left.updatedAt));
}

export async function createCadAnalysis(options: {
  workspacePath: string;
  modelPath: string;
  contextKey: string;
  revisionId: string | null;
  validatedAt: string | null;
  materialId: string | null;
  name: string;
  type: CadAnalysisType;
  solver: string;
  objective: string;
  loads: string;
  constraints: string;
  sshConnectionId?: string;
}): Promise<CadAnalysisManifest> {
  const now = new Date().toISOString();
  const manifest = cadAnalysisManifestSchema.parse({
    version: 1,
    id: crypto.randomUUID(),
    name: options.name.trim(),
    type: options.type,
    status: 'planned',
    model: {
      contextKey: options.contextKey,
      path: options.modelPath,
      revisionId: options.revisionId,
      validatedAt: options.validatedAt,
    },
    materialId: options.materialId,
    solver: options.solver.trim(),
    objective: options.objective.trim(),
    loads: options.loads.trim(),
    constraints: options.constraints.trim(),
    notes: '',
    files: [],
    createdAt: now,
    updatedAt: now,
  });
  const client = await getFilesClient();
  const root = cadAnalysisRootPath(options.modelPath);
  const folder = cadAnalysisFolderPath(options.modelPath, manifest.id);
  await ensureDirectoryTree(client, options, folder);
  const manifestPath = `${folder}/analysis.json`;
  await uploadJson(client, options, manifestPath, manifest);
  const existing = await loadIndex(client, options, root);
  await uploadJson(client, options, `${root}/index.json`, {
    version: 1,
    manifests: [...existing.manifests, manifestPath],
  });
  return manifest;
}

export async function saveCadAnalysis(
  options: { workspacePath: string; modelPath: string; sshConnectionId?: string },
  manifest: CadAnalysisManifest
): Promise<CadAnalysisManifest> {
  const next = cadAnalysisManifestSchema.parse({
    ...manifest,
    updatedAt: new Date().toISOString(),
  });
  const path = `${cadAnalysisFolderPath(options.modelPath, next.id)}/analysis.json`;
  await uploadJson(await getFilesClient(), options, path, next);
  return next;
}

export async function addCadAnalysisFile(
  options: { workspacePath: string; modelPath: string; sshConnectionId?: string },
  manifest: CadAnalysisManifest,
  file: File
): Promise<CadAnalysisManifest> {
  const client = await getFilesClient();
  const folder = cadAnalysisFolderPath(options.modelPath, manifest.id);
  const id = crypto.randomUUID();
  const name = safeFileName(file.name, id);
  const relativePath = `${folder}/${name}`;
  const uploaded = await client.fs.upload(
    { uri: analysisUri(options, relativePath), overwrite: false },
    {
      name,
      mimeType: file.type || 'application/octet-stream',
      size: file.size,
      lastModified: file.lastModified || Date.now(),
      source: file.stream(),
    }
  );
  if (!uploaded.success) throw new Error(fileError(uploaded.error));
  return await saveCadAnalysis(options, {
    ...manifest,
    files: [
      ...manifest.files,
      { id, name, role: analysisFileRole(name), relativePath, addedAt: new Date().toISOString() },
    ],
  });
}

async function loadIndex(
  client: Awaited<ReturnType<typeof getFilesClient>>,
  options: { workspacePath: string; modelPath: string; sshConnectionId?: string },
  root: string
): Promise<z.infer<typeof cadAnalysisIndexSchema>> {
  const path = `${root}/index.json`;
  const exists = await client.fs.exists({ uri: analysisUri(options, path) });
  if (!exists.success) throw new Error(fileError(exists.error));
  if (!exists.data.exists) return { version: 1, manifests: [] };
  return cadAnalysisIndexSchema.parse(
    JSON.parse(await readText(client, options, path, 'analysis index'))
  );
}

async function ensureDirectoryTree(
  client: Awaited<ReturnType<typeof getFilesClient>>,
  options: { workspacePath: string; sshConnectionId?: string },
  path: string
): Promise<void> {
  const segments = path.split('/').filter(Boolean);
  for (let index = 0; index < segments.length; index += 1) {
    const directory = segments.slice(0, index + 1).join('/');
    const uri = analysisUri(options, directory);
    const exists = await client.fs.exists({ uri });
    if (!exists.success) throw new Error(fileError(exists.error));
    if (exists.data.exists) continue;
    const created = await client.fs.createDirectory({ uri });
    if (!created.success) throw new Error(fileError(created.error));
  }
}

async function readText(
  client: Awaited<ReturnType<typeof getFilesClient>>,
  options: { workspacePath: string; sshConnectionId?: string },
  path: string,
  label: string
): Promise<string> {
  const result = await client.fs.readText({
    uri: analysisUri(options, path),
    options: { maxBytes: MAX_ANALYSIS_BYTES },
  });
  if (!result.success) throw new Error(fileError(result.error));
  if (result.data.truncated) throw new Error(`${label} exceeds the 256 KB limit.`);
  return result.data.content;
}

async function uploadJson(
  client: Awaited<ReturnType<typeof getFilesClient>>,
  options: { workspacePath: string; sshConnectionId?: string },
  path: string,
  value: unknown
): Promise<void> {
  const blob = new Blob([`${JSON.stringify(value, null, 2)}\n`], { type: 'application/json' });
  const uploaded = await client.fs.upload(
    { uri: analysisUri(options, path), overwrite: true },
    {
      name: path.split('/').at(-1) ?? 'analysis.json',
      mimeType: blob.type,
      size: blob.size,
      lastModified: Date.now(),
      source: blob.stream(),
    }
  );
  if (!uploaded.success) throw new Error(fileError(uploaded.error));
}

function analysisUri(
  options: { workspacePath: string; sshConnectionId?: string },
  relativePath: string
) {
  return encodeResourceUri(
    hostFileRefFromNativePath(
      resolveWorkspacePath(options.workspacePath, relativePath),
      options.sshConnectionId
    )
  );
}

function analysisFileRole(name: string): CadAnalysisFileRole {
  const lower = name.toLowerCase();
  if (/\.(?:inp|bdf|nas|fem|json|yaml|yml)$/.test(lower)) return 'input';
  if (/\.(?:msh|med|mesh)$/.test(lower)) return 'mesh';
  if (/\.(?:png|jpg|jpeg|webp|svg)$/.test(lower)) return 'image';
  if (/\.(?:pdf|md|html)$/.test(lower)) return 'report';
  return 'result';
}

function safeSegment(value: string, fallback: string): string {
  return (
    value
      .trim()
      .replace(/[^a-zA-Z0-9._-]+/g, '-')
      .replace(/^-+|-+$/g, '') || fallback
  );
}

function safeFileName(value: string, fallback: string): string {
  const base = value.split(/[\\/]/).at(-1) ?? fallback;
  return base.replace(/[^a-zA-Z0-9._ -]+/g, '-').replace(/^\.+/, '') || fallback;
}

function fileError(error: { type: string; message?: string }): string {
  return error.message ?? error.type;
}
