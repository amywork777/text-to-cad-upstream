"""Studio's ``cad mcp`` (``CAD_STUDIO_ENGINE=1``, cad_mcp/studio.py) starts this release's own server even where a
global cad is installed: never the installed cad's start, and never asks which cad is installed. Without it, the
installed cad's server, as Jake's rule says (``test_shim_start``). Nothing is started for real."""

from __future__ import annotations

import os
import unittest
from unittest import mock

from cad.engine import client
from cad_mcp import shim, studio


class StudioEngineTest(unittest.TestCase):
    def test_studio_s_starts_its_own_server_where_a_global_cad_is_installed(self) -> None:
        with mock.patch.dict(os.environ, {studio.ENV: "1"}), \
                mock.patch.object(shim, "installed_tool", side_effect=AssertionError("asked for the global cad")), \
                mock.patch.object(shim, "installed", side_effect=AssertionError("the installed cad's start")), \
                mock.patch.object(client, "AT_LEAST", None), \
                mock.patch.object(client, "start", return_value="started the cad server") as start:
            self.assertEqual(shim.start_server(), "started the cad server")
        start.assert_called_once_with()

    def test_without_it_the_installed_cad_s_server_is_started(self) -> None:
        tool = "/home/someone/.local/share/uv/tools/cad"
        for value in (None, "", "0"):
            env = {} if value is None else {studio.ENV: value}
            with self.subTest(value=value), mock.patch.dict(os.environ, env), \
                    mock.patch.object(shim, "installed_tool", return_value=tool), \
                    mock.patch.object(shim, "installed", return_value="joined the installed cad's") as installed, \
                    mock.patch.object(client, "AT_LEAST", None), \
                    mock.patch.object(client, "start", side_effect=AssertionError("its own server")):
                if value is None:
                    os.environ.pop(studio.ENV, None)
                self.assertEqual(shim.start_server(), "joined the installed cad's")
            installed.assert_called_once_with(tool)


if __name__ == "__main__":
    unittest.main()
