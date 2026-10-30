// pdf.js's worker, started as every viewer worker is (`new Worker(new URL(...))`), so an app that
// folds its workers into the page (the MCP app) takes this one too. Importing it is what starts it.
import "pdfjs-dist/build/pdf.worker.min.mjs";
