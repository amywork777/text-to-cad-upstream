export interface StarterCadModel {
  fileName: string;
  source: string;
}

export function createStarterCadModel(modelName: string): StarterCadModel {
  const slug = slugifyModelName(modelName) || 'untitled-model';
  const label = slug.replaceAll('-', '_');
  const functionName = /^\d/.test(label) ? `model_${label}` : label;

  return {
    fileName: `${slug}.py`,
    source: `"""Starter geometry for ${slug}. Revise this model from the Hardcore CAD workspace."""

from cadgen import build123d as bd
from cadgen import step


@step()
def ${functionName}(width: float = 40, depth: float = 30, height: float = 10):
    part = bd.Box(width, depth, height)
    part.label = "${label}"
    return part
`,
  };
}

export function slugifyModelName(modelName: string): string {
  return modelName
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '');
}
