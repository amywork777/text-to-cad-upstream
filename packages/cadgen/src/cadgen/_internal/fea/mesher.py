"""netgen in a process of its own: a BREP file in, the mesh's arrays out.

The ``netgen-mesher`` wheel brings its own OpenCascade (``netgen_occt``, 7.8) and cadgen runs on OCP's
OpenCascade 8. Loaded into one process, the two builds share symbols: a Boolean in OCP can crash after
netgen is imported, and the interpreter aborts on exit even when nothing crashed. So netgen is never
imported in cadgen's process. Each mesh is a child interpreter (``python -m cadgen._internal.fea.mesher
JOB RESULT``) that imports netgen and none of OCP: it reads the BREP the parent wrote, matches netgen's
faces to the parent's fingerprints (:func:`~cadgen._internal.fea.mesh.match_faces`), meshes
(:func:`~cadgen._internal.fea.mesh.generate_mesh`) and pickles copies of the arrays back.

Two jobs: a solid's volume mesh (:func:`volume`, the part and assembly meshers and the fluid domain's)
and a plate's top skin (:func:`skin`, the shell model's). A mesher error (a face that does not match, no
elements) is a RuntimeError in the parent with the child's message; a child that dies says so with the
end of what it printed.
"""

from __future__ import annotations

import os
import pickle
import subprocess
import sys
import tempfile
import traceback
from pathlib import Path
from typing import Any

__all__ = ["skin", "volume"]


def volume(brep: Path, prints: list, diagonal: float, h: float, refine: float, order: int, size_field: dict | None,
           *, origin: list[int] | None = None, keys: dict[Any, list] | None = None, count_domains: bool = False):
    """netgen's mesh of the solid in ``brep``: the verified face mapping (netgen face index -> fingerprint
    ordinal, through ``origin`` -- ``origin[ordinal - 1]`` -- when given), the nodes, the volume and surface
    elements, and (``count_domains``) the number of volumes. A size field's faces are keyed by ``keys``
    (mapped ordinal -> its keys; none: the ordinal itself)."""
    found = _run({"kind": "volume", "brep": str(brep), "prints": prints, "diagonal": diagonal, "h": h,
                  "refine": refine, "order": order, "size_field": size_field, "origin": origin, "keys": keys,
                  "count_domains": count_domains})
    return found["mapping"], found["coordinates"], found["e3"], found["e2"], found["domains"]


def skin(brep: Path, h: float, edge_h: float):
    """netgen's surface mesh of the faces in ``brep`` at ``h``, ``edge_h`` along every edge (``grading`` 0.3):
    the nodes and the linear triangles (0-based)."""
    found = _run({"kind": "skin", "brep": str(brep), "h": h, "edge_h": edge_h})
    return found["nodes"], found["triangles"]


def _run(job: dict) -> dict:
    import cadgen

    with tempfile.TemporaryDirectory(prefix="cadgen-mesher-") as tmp:
        job_path, result_path = Path(tmp) / "job.pickle", Path(tmp) / "result.pickle"
        job_path.write_bytes(pickle.dumps(job))
        # The child imports this cadgen, wherever it was imported from (an editable checkout, a wheel).
        source = str(Path(cadgen.__file__).resolve().parents[1])
        env = {**os.environ, "PYTHONPATH": os.pathsep.join(filter(None, [source, os.environ.get("PYTHONPATH")]))}
        done = subprocess.run([sys.executable, "-P", "-m", "cadgen._internal.fea.mesher", str(job_path), str(result_path)],
                              env=env, stdin=subprocess.DEVNULL, capture_output=True, text=True)
        if not result_path.is_file():
            said = (done.stderr or done.stdout).strip().splitlines()[-12:]
            raise RuntimeError(f"the mesher stopped (exit {done.returncode}) before it wrote a mesh"
                               + ("".join(f"\n  {line}" for line in said) if said else ""))
        found = pickle.loads(result_path.read_bytes())
    if "error" in found:
        raise RuntimeError(found["error"])
    return found


def _volume(job: dict) -> dict:
    import netgen.meshing as ngmesh
    import netgen.occ as ngocc
    import numpy as np

    from cadgen._internal.fea.mesh import generate_mesh, match_faces

    ngmesh.SetMessageImportance(0)
    geometry = ngocc.OCCGeometry(job["brep"])
    mapping = match_faces(job["prints"], list(geometry.faces), job["diagonal"])
    if job["origin"] is not None:
        mapping = {index: job["origin"][own - 1] for index, own in mapping.items()}
    keys = job["keys"]
    keys_of_face = {index: ([ordinal] if keys is None else list(keys.get(ordinal, ()))) for index, ordinal in mapping.items()}
    mesh = generate_mesh(geometry, ngocc, job["h"], job["refine"], job["order"], job["size_field"], keys_of_face)
    # Copies, deliberately: netgen hands out views into the mesh object's own memory.
    e3 = mesh.Elements3D().NumPy().copy()
    domains = None
    if job["count_domains"]:
        domains = int(mesh.GetNDomains()) if hasattr(mesh, "GetNDomains") else int(e3["index"].max())
    return {"mapping": mapping, "coordinates": np.array(mesh.Coordinates(), dtype=float, copy=True), "e3": e3,
            "e2": mesh.Elements2D().NumPy().copy(), "domains": domains}


def _skin(job: dict) -> dict:
    import netgen.meshing as ngmesh
    import netgen.occ as ngocc
    import numpy as np

    ngmesh.SetMessageImportance(0)
    shape = ngocc.OCCGeometry(job["brep"]).shape
    for edge in shape.edges:
        edge.maxh = float(job["edge_h"])
    mesh = ngocc.OCCGeometry(shape).GenerateMesh(maxh=float(job["h"]), grading=0.3)
    return {"nodes": np.array(mesh.Coordinates(), dtype=float, copy=True),
            "triangles": mesh.Elements2D().NumPy()["nodes"][:, :3].astype(np.int64) - 1}


def main(argv: list[str]) -> int:
    job_path, result_path = Path(argv[0]), Path(argv[1])
    job = pickle.loads(job_path.read_bytes())
    try:
        from cadgen._internal.fea.mesh import kernel_messages_on_stderr

        with kernel_messages_on_stderr():
            found = (_volume if job["kind"] == "volume" else _skin)(job)
    except RuntimeError as error:
        found = {"error": str(error)}
    except Exception as error:  # noqa: BLE001 -- said in the parent, with where it came from
        found = {"error": f"the mesher failed: {type(error).__name__}: {error}\n{traceback.format_exc()}"}
    result_path.write_bytes(pickle.dumps(found))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
