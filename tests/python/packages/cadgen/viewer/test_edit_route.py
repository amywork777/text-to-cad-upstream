"""Edit mode's routes, `/__cad/edit/state` and `/__cad/edit/change`: POSTs behind the viewer's own
guard, answered as JSON whatever they meet (the edit service itself is tested in ``test_edit``)."""

from __future__ import annotations

import http.client
import json
import os
import shutil
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

from cadgen.viewer import handler as handler_module
from cadgen.viewer.http_app import create_cad_app


class EditRoutesTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        environment = mock.patch.dict(os.environ, {"CADGEN_STATE_DIR": str(self.tmp / "state")})
        environment.start()
        self.addCleanup(environment.stop)
        server = handler_module.serve(create_cad_app(host="127.0.0.1", port=0), "127.0.0.1", 0)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(thread.join, 5)
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        self.port = server.server_address[1]

    def post(self, path: str, body: object, *, guard: bool = True) -> tuple[int, object]:
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        try:
            headers = {"content-type": "application/json"}
            if guard:
                headers["x-cadgen-viewer"] = "1"
            connection.request("POST", path, body=json.dumps(body), headers=headers)
            response = connection.getresponse()
            data = response.read()
            return response.status, json.loads(data) if data else None
        finally:
            connection.close()

    def test_a_model_without_a_part_script_answers_that_it_has_none(self) -> None:
        status, body = self.post("/__cad/edit/state", {"file": str(self.tmp / "imported.step")})
        self.assertEqual(status, 200)
        self.assertEqual((body["ok"], body["reason"]), (False, "no-script"))

    def test_a_probe_says_whether_there_is_a_part_script_without_running_it(self) -> None:
        script = self.tmp / "plate.py"
        script.write_text("from cadgen import model\n\n@model\ndef plate():\n    raise SystemExit('never run')\n", encoding="utf-8")
        status, body = self.post("/__cad/edit/state", {"file": str(self.tmp / "plate.step"), "probe": True})
        from cadgen.engine.ids import model_id

        # Never built, and no build of it queued: nothing to open yet, and nothing to wait for.
        self.assertEqual((status, body), (200, {"ok": True, "editable": True, "document": model_id(script, "plate"),
                                                "partBuilt": False, "partBuilding": False}))
        _, none = self.post("/__cad/edit/state", {"file": str(self.tmp / "imported.step"), "probe": True})
        self.assertEqual(none, {"ok": True, "editable": False})

    def test_a_face_of_a_model_without_a_part_script_names_no_feature(self) -> None:
        status, body = self.post("/__cad/edit/face", {"file": str(self.tmp / "imported.step"), "face": 3})
        self.assertEqual(status, 200)
        self.assertEqual((body["ok"], body["reason"]), (False, "no-script"))

    def test_a_bad_request_is_an_answer_not_a_crash(self) -> None:
        status, body = self.post("/__cad/edit/change", ["not", "an", "object"])
        self.assertEqual(status, 200)
        self.assertFalse(body["ok"])

    def test_a_request_without_the_viewer_guard_is_refused(self) -> None:
        status, _ = self.post("/__cad/edit/state", {"file": str(self.tmp / "imported.step")}, guard=False)
        self.assertGreaterEqual(status, 400)


if __name__ == "__main__":
    unittest.main()
