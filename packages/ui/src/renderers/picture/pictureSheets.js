/**
 * A picture file as the sheets a flat view paints: a PNG, JPEG or WebP is one sheet, a PDF a sheet
 * per page (an engineering drawing's sheets), stacked top to bottom with a gap between, as a
 * reader scrolls them. A sheet is a bitmap and its size in the view's units: an image's pixels, a
 * PDF's points, so a drawing reads at its printed size at 100% and a page is rendered sharper than
 * that to stay crisp as the person zooms in.
 *
 * Coordinates are the flat view's (`@text-to-cad/core/lib/drawing2d/transform.js`: y up), so the
 * first sheet's top-left corner is the origin and the sheets go down into negative y.
 */

/** A PDF's pages: what may be read, and how sharp each is rendered, past its printed size. */
export const PDF_FILE = /\.pdf$/i;
const PDF_RENDER_SCALE = 2;
/** The most pixels one rendered page may hold: a large sheet is rendered less sharp, not refused. */
const MAX_SHEET_PIXELS = 6000 * 6000;
/** The gap between a PDF's sheets, in the view's units. */
export const SHEET_GAP = 24;

let pdfWorker = null;

/** pdf.js, loaded the first time a PDF is opened, with its worker (`pdfWorker.js`) started once. */
async function loadPdf() {
  const pdfjs = await import("pdfjs-dist");
  if (!pdfWorker) {
    pdfWorker = new Worker(new URL("./pdfWorker.js", import.meta.url), { type: "module" });
    pdfjs.GlobalWorkerOptions.workerPort = pdfWorker;
  }
  return pdfjs;
}

/** A page rendered to a bitmap, sharper than printed, no larger than `MAX_SHEET_PIXELS`. */
async function renderPage(page) {
  const printed = page.getViewport({ scale: 1 });
  const area = printed.width * printed.height * PDF_RENDER_SCALE * PDF_RENDER_SCALE;
  const scale = area > MAX_SHEET_PIXELS ? Math.sqrt(MAX_SHEET_PIXELS / (printed.width * printed.height)) : PDF_RENDER_SCALE;
  const viewport = page.getViewport({ scale });
  const canvas = document.createElement("canvas");
  canvas.width = Math.max(1, Math.round(viewport.width));
  canvas.height = Math.max(1, Math.round(viewport.height));
  await page.render({ canvas, viewport }).promise;
  const bitmap = await createImageBitmap(canvas);
  return { bitmap, width: printed.width, height: printed.height };
}

/**
 * The sheets of the picture in `bytes`, read as `file` names it, each with its place (`top`, in the
 * view's units, from the first sheet's top), and the bounds that frame them all.
 * @param {ArrayBuffer} bytes
 * @param {string} file
 * @param {{ signal?: AbortSignal }} [options]
 */
export async function readSheets(bytes, file, { signal } = {}) {
  let sheets;
  if (PDF_FILE.test(file)) {
    const pdfjs = await loadPdf();
    const loading = pdfjs.getDocument({ data: new Uint8Array(bytes), isEvalSupported: false });
    try {
      const pdf = await loading.promise;
      sheets = [];
      for (let number = 1; number <= pdf.numPages; number += 1) {
        if (signal?.aborted) throw signal.reason ?? new Error("The picture was closed.");
        sheets.push(await renderPage(await pdf.getPage(number)));
      }
    } finally {
      void loading.destroy();
    }
  } else {
    const bitmap = await createImageBitmap(new Blob([bytes]));
    sheets = [{ bitmap, width: bitmap.width, height: bitmap.height }];
  }
  return layoutSheets(sheets);
}

/**
 * Sheets placed top to bottom, `SHEET_GAP` apart, and the bounds that frame them
 * (`[minX, minY, maxX, maxY]`, y up).
 * @param {readonly { bitmap: CanvasImageSource, width: number, height: number }[]} sheets
 */
export function layoutSheets(sheets) {
  let top = 0, width = 0;
  const placed = sheets.map((sheet) => {
    const at = { ...sheet, top };
    top += sheet.height + SHEET_GAP;
    width = Math.max(width, sheet.width);
    return at;
  });
  const height = Math.max(0, top - SHEET_GAP);
  return { sheets: placed, bounds: placed.length ? [0, -height, width, 0] : null };
}

/**
 * Paints `picture`'s sheets under `transform` (`scale`, `offsetX`, `offsetY`: a unit at (x, y) is
 * at screen (x·scale + offsetX, −y·scale + offsetY)), in CSS pixels on a backing store `pixelRatio`
 * times as dense.
 * @param {CanvasRenderingContext2D} ctx
 * @param {{ sheets: readonly { bitmap: CanvasImageSource, width: number, height: number, top: number }[] }} picture
 * @param {{ transform: { scale: number, offsetX: number, offsetY: number }, pixelRatio?: number }} view
 */
export function paintSheets(ctx, picture, { transform, pixelRatio = 1 }) {
  ctx.save();
  ctx.setTransform(pixelRatio, 0, 0, pixelRatio, 0, 0);
  ctx.imageSmoothingQuality = "high";
  for (const sheet of picture.sheets) {
    ctx.drawImage(sheet.bitmap, transform.offsetX, sheet.top * transform.scale + transform.offsetY,
      sheet.width * transform.scale, sheet.height * transform.scale);
  }
  ctx.restore();
}
