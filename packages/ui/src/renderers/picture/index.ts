import type { ComponentType } from 'react';
import { defineFileRenderer } from '../../file-viewer/registry.js';
import type { FileRendererProps } from '../../file-viewer/types.js';
import type { LiveViewBinding } from '../kit/shell/liveBinding.js';
import { createCadPreferences, prepareWorkspaceEntry } from '../workspace/index.js';
import type { CadPreferenceSource, PreparedWorkspaceEntry, ViewerCommandSource, WorkspaceClientOption } from '../workspace/index.js';

export interface PictureRendererOptions {
  client: WorkspaceClientOption;
  preferences?: CadPreferenceSource;
  /** Host requests. One to select a reference is consumed and declined in words: a picture has none. */
  commands?: ViewerCommandSource;
  /** The mounted view's live command surface. Camera, Display and select commands are declined, loudly. */
  live?: LiveViewBinding<any>;
}
export interface PreparedPictureDocument extends PreparedWorkspaceEntry {
  services: Omit<PictureRendererOptions, 'client'> & { preferences: CadPreferenceSource };
}

/** The engineering pictures: a drawing's PDF, a render or a photo (cadgen's `PICTURE_EXTENSIONS`). */
export const PICTURE_FILE = /\.(?:pdf|png|jpe?g|webp)$/i;

/**
 * A picture is shown as a drawing is, on a flat view (`kit/shell/FlatViewFrame.jsx`), so it is
 * marked up and sent the same way: Pencil and Shapes draw on it, Quick Edit sends the marks with a
 * note. A PDF is a sheet per page. The bytes are the file's own, as the catalog serves them; pdf.js
 * reads a PDF in a worker of its own, loaded only when one is opened.
 */
export function createPictureRenderer({ client, ...options }: PictureRendererOptions) {
  const services = { ...options, preferences: options.preferences || createCadPreferences() };
  return defineFileRenderer<PreparedPictureDocument>({
    id: 'picture',
    priority: 100,
    matches: (file) => PICTURE_FILE.test(file.path),
    async prepare(context) {
      const prepared = await prepareWorkspaceEntry(client, context);
      return { ...prepared, data: { ...prepared.data, services } };
    },
    load: () => import('./PictureRenderer.jsx') as Promise<{ default: ComponentType<FileRendererProps<PreparedPictureDocument>> }>
  });
}
