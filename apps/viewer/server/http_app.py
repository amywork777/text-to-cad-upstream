"""The HTTP contract: both browser gates, route dispatch, and the SPA.

Security / trust model, unchanged from the Node backend: the server binds
loopback and serves UNAUTHENTICATED — the loopback bind is the trust boundary
against other processes and machines. Loopback is NOT a boundary against the
user's own browser, so two gates defend against that specifically:

* Host validation refuses a request whose Host names anything but
  127.0.0.1/localhost/::1 — the DNS-rebinding case, where an attacker domain
  re-resolves to loopback and the browser treats us as same-origin. Skipped when
  bound non-loopback, matching Jupyter's ``allow_remote_access``.
* Every POST requires an ``x-cadgen-viewer`` header. ``POST /__cad/artifact``
  compiles the target, and since all params ride the query string with no body,
  a cross-origin POST is otherwise a no-preflight "simple request". A custom
  header forces a preflight instead.

No ``Access-Control-*`` headers are served, deliberately: their absence is what
makes the same-origin policy block cross-origin reads and what makes that
preflight fail. Do not add them.

PORT STATUS: this module carries the routing table, both gates, ``serverInfo``,
the static/SPA half, the catalog and the asset/store routes. The artifact-status
machinery, reveal and the tessellation cache are wired in later steps of the
port; each is registered here and answers 501 with a distinctive body until
then, so a missing route can never be mistaken for a working one.
"""

from __future__ import annotations

import json
import os
import stat
import threading
import time
from pathlib import Path

from .backend import ForbiddenAssetError, LocalAssetBackend
from .content_types import content_type_for_static_asset
from .encoding import UriError, attachment_content_disposition, strict_decode_uri_component
from .scanner import node_basename, path_relative
from .store_paths import store_packages_dir

__all__ = [
    "CadApp",
    "ForbiddenAssetError",
    "POST_GUARD_HEADER",
    "LOCAL_SERVER_FEATURES",
    "hostname_only",
    "host_is_allowed",
    "read_viewer_version",
    "create_cad_app",
]

POST_GUARD_HEADER = "x-cadgen-viewer"
LOCAL_SERVER_FEATURES = ["path-directory"]
_LOOPBACK_NAMES = frozenset({"127.0.0.1", "localhost", "::1"})

TESS_CACHE_ROUTE_PREFIX = "/__tess_cache/"
TESS_CACHE_BATCH_PATH = "/__tess_cache/batch"

_PACKAGE_DIR = str(Path(__file__).resolve().parent)


def hostname_only(host_header) -> str:
    value = str(host_header or "").strip()
    if value.startswith("["):
        end = value.find("]")
        return (value[1:end] if end != -1 else value).lower()
    index = value.rfind(":")
    if index != -1 and _is_ascii_digits(value[index + 1 :]):
        return value[:index].lower()
    return value.lower()


def host_is_allowed(host_header, bound_host) -> bool:
    """DNS-rebinding defense.

    The NAME is compared, never the port: the attack requires a non-local name,
    and ignoring the port keeps odd-port instances and the dev proxy working.
    Skipped when the operator bound a non-loopback interface — they have
    deliberately left the loopback trust model. An absent Host header is
    allowed: HTTP/1.0 clients omit it, and the browser (the threat this exists
    for) always sends it.
    """
    if hostname_only(bound_host) not in _LOOPBACK_NAMES:
        return True
    if not str(host_header or "").strip():
        return True
    return hostname_only(host_header) in _LOOPBACK_NAMES


def read_viewer_version() -> str:
    """``package.json``'s version, ``""`` on any failure.

    Exported for the launcher's reuse key (realpath(root) x version): both sides
    of that comparison must read the version the same way, and the bundled
    runtime's package.json is the one file that carries it.
    """
    try:
        package_json = Path(__file__).resolve().parent.parent / "package.json"
        return str(json.loads(package_json.read_text(encoding="utf-8")).get("version") or "")
    except Exception:  # noqa: BLE001 - a malformed package.json is not fatal
        return ""


def _is_ascii_digits(value: str) -> bool:
    """JS ``/^\\d+$/``: ASCII only.

    ``str.isdigit()`` is Unicode-aware and would treat ``[::1]:٢`` as a port.
    """
    return bool(value) and value.isascii() and value.isdigit()


class CadApp:
    """``handle(request, response)`` writes exactly one response.

    Unlike the Node app there is no "not mine" return: the Python server always
    serves the client itself, and the dev proxy forwards only the two API
    prefixes, so nothing else can be waiting behind this.
    """

    def __init__(self, *, root: str, host: str, port: int, dist_dir: str = ""):
        self.backend = LocalAssetBackend(root)
        root_path = self.backend.root_path
        self.root_path = root_path
        self.root_name = self.backend.root_name
        self.host = host
        self.port = port
        # dist_dir is compared as a string prefix, so resolve it ONCE here and
        # never re-resolve at request time.
        self.dist_dir = os.path.abspath(dist_dir) if dist_dir else ""
        self.viewer_version = read_viewer_version()
        self.started_at = time.time()
        self.lock = threading.Lock()

    # --- server info ------------------------------------------------------

    def server_info(self) -> dict:
        return {
            "app": "cad-viewer",
            "viewerVersion": self.viewer_version,
            "serverMode": "serve",
            "serverFeatures": LOCAL_SERVER_FEATURES,
            "backend": "local-fs",
            # path.resolve(), NOT realpath: the launcher's registry and the
            # client both compare the spelling the operator gave.
            "rootPath": self.root_path,
            "rootName": self.root_name,
            "port": self.port,
            "pid": os.getpid(),
            # The viewer is a static visualization tool: it never runs
            # generators or exports. The CLIs own those; this stays false.
            "stepArtifactGenerationAvailable": False,
            "stepImportAvailable": self.step_import_available(),
            "packageDir": _PACKAGE_DIR,
            "startedAt": self.started_at,
            "url": f"http://{self.host}:{self.port}",
        }

    def step_import_available(self) -> bool:
        """Whether a foreign STEP can be imported.

        Wired to a real ``cadgen`` probe in the cadgen-integration step. It must
        stay a probe rather than becoming a constant ``True``: a viewer launched
        by an interpreter without cadgen has to degrade to viewing-only.
        """
        return False

    # --- gates ------------------------------------------------------------

    def _rejected_by_host_check(self, request, response) -> bool:
        host_header = request.header("host")
        if host_is_allowed(host_header, self.host):
            return False
        response.send_json(
            403,
            {
                "error": (
                    f"Host header '{hostname_only(host_header)}' is not a local name; "
                    "refusing (DNS-rebinding defense)"
                )
            },
        )
        return True

    def _rejected_as_cross_site_post(self, request, response) -> bool:
        if request.header(POST_GUARD_HEADER):
            return False
        response.send_json(
            403,
            {
                "error": (
                    f"missing {POST_GUARD_HEADER} header (cross-site POST blocked); "
                    f"send '{POST_GUARD_HEADER}: 1'"
                )
            },
        )
        return True

    # --- static dist + SPA ------------------------------------------------

    def _serve_file(self, response, file_path, content_type) -> bool:
        try:
            stat_result = os.stat(file_path)
        except (OSError, ValueError):
            # ValueError: a path carrying a NUL byte. Node's statSync throws
            # and the throw is caught, falling through to the SPA at 200.
            return False
        if not os.path.isfile(file_path):
            return False
        response.stream_file(file_path, stat_result, content_type or "")
        return True

    def _serve_dist(self, request, response) -> None:
        """Static dist + SPA fallback.

        The page lives at ``/`` and nothing else here is a directory, so this is
        an ordinary static server: serve the file if the bundle has it,
        otherwise fall back to index.html — EXCEPT under ``/assets/``, where a
        miss must be a 404 rather than HTML, or a stale hashed bundle reference
        turns into an ES-module parse error instead of a readable status.
        """
        if not self.dist_dir:
            # No built client. Answering here rather than joining against an
            # empty base is load-bearing: os.path.join("", x) resolves against
            # the CURRENT WORKING DIRECTORY, which would silently turn the
            # viewer into a static server for wherever it was launched from.
            response.send_plain(404, "Not found")
            return
        pathname = request.path
        request_path = "/index.html" if pathname == "/" else pathname
        try:
            decoded = strict_decode_uri_component(request_path)
        except UriError:
            response.send_plain(400, "Bad request")
            return
        file_path = os.path.abspath(os.path.join(self.dist_dir, decoded.lstrip("/")))
        if not (file_path == self.dist_dir or file_path.startswith(self.dist_dir + os.sep)):
            response.send_plain(403, "Forbidden")
            return
        if self._serve_file(response, file_path, content_type_for_static_asset(file_path)):
            return
        if request_path.startswith("/assets/"):
            response.send_plain(404, "Not found")
            return
        index_html = os.path.join(self.dist_dir, "index.html")
        if not self._serve_file(response, index_html, content_type_for_static_asset(index_html)):
            response.send_plain(404, "Not found")

    # --- routes still to be ported ----------------------------------------

    @staticmethod
    def _not_ported(response, name: str) -> None:
        """Answer 501 with a distinctive body.

        A placeholder that 404s or 200s would be indistinguishable from a
        working route; 501 with the route name in it cannot be mistaken for
        either while the port is in flight.
        """
        response.send_json(501, {"ok": False, "error": f"route not yet ported: {name}"})

    # --- dispatch ---------------------------------------------------------

    def handle(self, request, response) -> None:
        method = request.method
        pathname = request.path
        query = request.query

        if method == "GET":
            if self._rejected_by_host_check(request, response):
                return
            if pathname.startswith(TESS_CACHE_ROUTE_PREFIX):
                # Shared component-tessellation cache. Checked BEFORE the dist
                # fallthrough: this is an API family, not a page asset.
                self._handle_tess_get(request, response)
                return
            if not pathname.startswith("/__cad/"):
                # Note "/__cad" without the trailing slash is NOT an API path
                # and falls through to the SPA at 200, while "/__cad/" is and
                # answers 404 JSON. Both are the shipped behaviour.
                self._serve_dist(request, response)
                return
            try:
                if pathname == "/__cad/server":
                    response.send_json(200, self.server_info())
                elif pathname == "/__cad/catalog":
                    self._handle_catalog(request, response)
                elif pathname == "/__cad/artifact":
                    self._handle_artifact_status(request, response, query)
                elif pathname == "/__cad/store":
                    self._handle_store_asset(request, response, query)
                elif pathname == "/__cad/asset":
                    self._handle_asset(request, response, query, download=False)
                elif pathname == "/__cad/download":
                    self._handle_asset(request, response, query, download=True)
                else:
                    # An unrecognised /__cad/* path is a bad API call, not a
                    # page. Falling through to the SPA answered typo'd and
                    # retired routes with index.html at 200, so a client doing
                    # res.json() got an HTML parse error instead of a status.
                    response.send_json(404, {"error": "Not found"})
            except ForbiddenAssetError:
                response.send_json(403, {"error": "Forbidden"})
            except Exception as error:  # noqa: BLE001
                response.send_json(400, {"error": str(error)})
            return

        if method == "POST":
            # Gated before dispatch, not per route, so a POST route added later
            # is covered by construction.
            if self._rejected_by_host_check(request, response):
                return
            if self._rejected_as_cross_site_post(request, response):
                return
            try:
                if pathname == "/__cad/artifact":
                    self._handle_artifact_build(request, response, query)
                elif pathname == "/__cad/reveal":
                    self._handle_reveal(request, response, query)
                elif pathname == TESS_CACHE_BATCH_PATH:
                    # Matched BEFORE the prefix branch: /__tess_cache/batch
                    # matches both.
                    self._handle_tess_batch(request, response)
                elif pathname.startswith(TESS_CACHE_ROUTE_PREFIX):
                    self._handle_tess_post(request, response)
                else:
                    response.send_empty(405, [("allow", "POST")])
            except ForbiddenAssetError:
                response.send_json(403, {"error": "Forbidden"})
            except Exception as error:  # noqa: BLE001
                # Note the asymmetry with the GET funnel: this one carries
                # ok:false and that one does not.
                response.send_json(400, {"ok": False, "error": str(error)})
            return

        # Unreachable: handler.py answers 405 for every other method before
        # dispatch ever runs.
        response.send_empty(405, [("allow", "GET, HEAD, POST")])

    # --- placeholders filled by later steps of the port -------------------

    def _handle_catalog(self, request, response):
        response.send_json(200, self.backend.read_catalog())

    def _handle_artifact_status(self, request, response, query):
        self._not_ported(response, "GET /__cad/artifact")

    def _handle_artifact_build(self, request, response, query):
        self._not_ported(response, "POST /__cad/artifact")

    def _handle_store_asset(self, request, response, query):
        """Render-package assets, confined to the store's ``packages/`` tier.

        Everything that fails here is 404, never 403: the containment failure is
        folded into "there is no stat" rather than raised. Leading slashes are
        STRIPPED because the client's resolvePackageAssetUrl emits
        ``file=/<key>/components/c0.surf``; that also means ``file=/etc/hosts``
        resolves under the tier and 404s rather than reading /etc/hosts.
        """
        rel = str(query.get("file") or "").replace("\\", "/")
        base = os.path.abspath(store_packages_dir())
        candidate = os.path.abspath(os.path.join(base, rel.lstrip("/")))
        contained = candidate == base or candidate.startswith(base + os.sep)
        hidden = any(
            part and part != ".." and part.startswith(".")
            for part in path_relative(base, candidate).split(os.sep)
        )
        stat_result = None
        if contained and not hidden:
            try:
                stat_result = os.stat(candidate)
            except (OSError, ValueError):
                stat_result = None
        # One stat answers both existence and regular-ness; re-statting would
        # open a window where the two disagree.
        if stat_result is None or not stat.S_ISREG(stat_result.st_mode):
            response.send_json(404, {"error": "Not found"})
            return
        content_type = self.backend.content_type_for_path(candidate) or "application/octet-stream"
        response.stream_file(candidate, stat_result, content_type)

    def _handle_asset(self, request, response, query, *, download):
        candidate = self.backend.asset_path_for_file_ref(query.get("file") or "")
        stat_result = None
        if candidate:
            try:
                stat_result = os.stat(candidate)
            except (OSError, ValueError):
                stat_result = None
        if not candidate or stat_result is None or not stat.S_ISREG(stat_result.st_mode):
            response.send_json(404, {"error": "Not found"})
            return
        content_type = self.backend.content_type_for_path(candidate) or "application/octet-stream"
        disposition = (
            attachment_content_disposition(node_basename(candidate)) if download else None
        )
        response.stream_file(candidate, stat_result, content_type, disposition=disposition)

    def _handle_reveal(self, request, response, query):
        self._not_ported(response, "POST /__cad/reveal")

    def _handle_tess_get(self, request, response):
        self._not_ported(response, "GET /__tess_cache/*")

    def _handle_tess_post(self, request, response):
        self._not_ported(response, "POST /__tess_cache/*")

    def _handle_tess_batch(self, request, response):
        self._not_ported(response, "POST /__tess_cache/batch")


def create_cad_app(*, root: str, host: str, port: int, dist_dir: str = "") -> CadApp:
    return CadApp(root=root, host=host, port=port, dist_dir=dist_dir)
