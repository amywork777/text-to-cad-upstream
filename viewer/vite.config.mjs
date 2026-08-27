import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

import { createCadApp } from "./server/httpApp.mjs";
import { resolveDirectoryRoot as resolveViewerDirectoryRoot } from "./scripts/directoryRoot.mjs";
import { resolveServerFsAllow } from "./scripts/serverFsAllow.mjs";
import { assertNoDeprecatedLocalRootEnv } from "./scripts/viewerEnv.mjs";
import {
  normalizeServerLifetimeMs,
  scheduleProcessShutdown,
} from "./scripts/serverLifetime.mjs";

const DEFAULT_VIEWER_PORT = 3245;

const viewerAppRoot = path.dirname(fileURLToPath(import.meta.url));
const viewerClientRoot = path.join(viewerAppRoot, "src", "client");
const cadJsPackageRoot = resolveCadJsPackageRoot();
const viewerNodeModulesRoot = path.join(viewerAppRoot, "node_modules");
const defaultDirectoryRoot = path.resolve(viewerAppRoot, "..");
const directoryRoot = resolveDirectoryRoot();
const viewerAllowedHosts = normalizeViewerAllowedHosts(process.env.VIEWER_ALLOWED_HOSTS ?? "");
const viewerServerLifetimeMs = normalizeServerLifetimeMs(process.env.VIEWER_SERVER_LIFETIME_MS);
assertNoDeprecatedLocalRootEnv(process.env);

function normalizeViewerAllowedHosts(value) {
  return String(value || "")
    .split(",")
    .map((host) => host.trim())
    .filter(Boolean);
}

function readViewerPackageVersion(appRoot) {
  try {
    const packageJson = JSON.parse(fs.readFileSync(path.join(appRoot, "package.json"), "utf8"));
    return String(packageJson.version || "");
  } catch {
    return "";
  }
}

function findRootPackageSrc(packageDirName) {
  let current = viewerAppRoot;
  for (;;) {
    const candidate = path.join(current, "packages", packageDirName, "src");
    if (
      fs.existsSync(candidate) &&
      fs.existsSync(path.join(current, "packages", packageDirName, "package.json"))
    ) {
      return candidate;
    }
    const next = path.dirname(current);
    if (next === current) {
      return "";
    }
    current = next;
  }
}

function resolveCadJsPackageRoot() {
  const bundledPackageSrc = path.join(viewerAppRoot, "packages", "cadjs", "src");
  if (fs.existsSync(bundledPackageSrc)) {
    return bundledPackageSrc;
  }
  const rootPackageSrc = findRootPackageSrc("cadjs");
  if (rootPackageSrc) {
    return rootPackageSrc;
  }
  const installedPackageSrc = path.join(viewerAppRoot, "node_modules", "cadjs", "src");
  if (fs.existsSync(installedPackageSrc)) {
    return installedPackageSrc;
  }
  // Nothing resolved: name the in-app path so the failure points at this
  // checkout rather than escaping to a parent workbench that may not exist.
  return bundledPackageSrc;
}

function resolveDirectoryRoot() {
  return resolveViewerDirectoryRoot({
    env: process.env,
    cwd: process.cwd(),
    appRoot: viewerAppRoot,
    defaultDirectoryRoot,
  });
}

// Dev mode runs the SAME JS backend as production, in-process: Vite serves the
// client (with HMR) and this middleware answers /__cad/* directly. No second
// process, no proxy, no Python at startup — cadgen is spawned per build/export
// by the backend itself, only when a request needs it.
function cadViewerBackendPlugin() {
  return {
    name: "cad-viewer-backend",
    configureServer(server) {
      const devPort = server.config.server?.port;
      const app = createCadApp({
        root: directoryRoot,
        host: "127.0.0.1",
        port: devPort || DEFAULT_VIEWER_PORT,
      });
      server.middlewares.use((req, res, next) => {
        app.handle(req, res).then(
          (handled) => {
            if (!handled) {
              next();
            }
          },
          (error) => {
            if (!res.headersSent) {
              res.statusCode = 500;
            }
            res.end(`CAD Viewer backend error: ${error?.message || error}`);
          },
        );
      });
    },
  };
}

function serverLifetimePlugin() {
  return {
    name: "cad-viewer-server-lifetime",
    configureServer(server) {
      if (viewerServerLifetimeMs === null) {
        return;
      }
      let shutdownTimer = null;
      const scheduleShutdown = () => {
        shutdownTimer = scheduleProcessShutdown({
          lifetimeMs: viewerServerLifetimeMs,
          label: "CAD Viewer dev server",
          close: () => server.close(),
        });
      };
      if (server.httpServer?.listening) {
        scheduleShutdown();
      } else {
        server.httpServer?.once("listening", scheduleShutdown);
      }
      server.httpServer?.once("close", () => {
        if (shutdownTimer) {
          clearTimeout(shutdownTimer);
        }
      });
    },
  };
}

export default defineConfig(({ command }) => ({
  root: viewerAppRoot,
  envPrefix: "VIEWER_",
  plugins: [
    react(),
    cadViewerBackendPlugin(),
    serverLifetimePlugin(),
  ],
  resolve: {
    alias: {
      "@": viewerClientRoot,
      "cadjs": cadJsPackageRoot,
      "clsx": path.join(viewerNodeModulesRoot, "clsx"),
      "gifenc": path.join(viewerNodeModulesRoot, "gifenc", "dist", "gifenc.esm.js"),
      "tailwind-merge": path.join(viewerNodeModulesRoot, "tailwind-merge"),
      "three": path.join(viewerNodeModulesRoot, "three"),
      "three/examples": path.join(viewerNodeModulesRoot, "three", "examples"),
    },
  },
  esbuild: {
    loader: "jsx",
    include: /.*\.[jt]sx?$/,
    exclude: [],
  },
  optimizeDeps: {
    esbuildOptions: {
      loader: {
        ".js": "jsx",
      },
    },
  },
  build: {
    chunkSizeWarningLimit: 800,
    rollupOptions: {
      output: {
        manualChunks(id) {
          if (!id.includes("node_modules")) {
            return undefined;
          }
          if (id.includes("/three/")) {
            return "vendor-three";
          }
          if (id.includes("/react/") || id.includes("/react-dom/")) {
            return "vendor-react";
          }
          if (id.includes("/radix-ui/") || id.includes("/@radix-ui/")) {
            return "vendor-ui";
          }
          if (id.includes("/lucide-react/")) {
            return "vendor-icons";
          }
          return undefined;
        },
      },
    },
  },
  worker: {
    format: "es",
  },
  server: {
    host: "127.0.0.1",
    port: DEFAULT_VIEWER_PORT,
    // Fail on a taken port instead of silently rolling to the next one, so dev
    // matches `npm run start`: a Viewer is always on the port you asked for.
    strictPort: true,
    allowedHosts: viewerAllowedHosts,
    fs: {
      // Real paths too: Vite checks ids after resolution, and the develop layout
      // reaches cadjs through a symlink. See scripts/serverFsAllow.mjs.
      allow: resolveServerFsAllow([viewerAppRoot, cadJsPackageRoot], {
        realpath: fs.realpathSync,
      }),
    },
  },
  preview: {
    host: "127.0.0.1",
    allowedHosts: viewerAllowedHosts,
  },
}));
