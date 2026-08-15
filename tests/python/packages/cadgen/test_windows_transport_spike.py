"""PHASE 0 SPIKE — TEMPORARY, delete once the Windows transport lands.

The daemon speaks AF_UNIX, which CPython does not provide on Windows. The replacement
under consideration is multiprocessing.connection, which offers AF_PIPE (Windows named
pipes) and AF_UNIX from one API, with an authkey HMAC handshake.

Three questions decide whether that plan is viable, and none can be answered from a POSIX
machine. This runs on every platform so the Windows answers have a baseline to be read
against:

1. Does the platform actually offer a pipe/socket family through this API, and does a
   round-trip work between two PROCESSES (not two threads in one)?
2. Can several clients hold connections to one Listener at once? A pipe server needs a
   fresh instance per client on Windows, and a pool that cannot serve concurrent callers
   is not worth porting.
3. Does a detached child outlive the process that spawned it? `start_new_session=True` is
   silently ignored on Windows (it is literally named `unused_start_new_session` in
   subprocess), so the daemon would otherwise share its parent's console and die with it.

Findings are printed so the CI log carries the answers even when everything passes.
"""

from __future__ import annotations

import multiprocessing.connection as mpc
import os
import socket
import subprocess
import sys
import tempfile
import textwrap
import time
import unittest
from pathlib import Path

CLIENT_SOURCE = textwrap.dedent(
    """
    import sys, multiprocessing.connection as mpc
    address, key_hex, payload = sys.argv[1], sys.argv[2], sys.argv[3]
    conn = mpc.Client(address, authkey=bytes.fromhex(key_hex))
    conn.send_bytes(payload.encode())
    echoed = conn.recv_bytes()
    conn.close()
    sys.exit(0 if echoed == payload.upper().encode() else 3)
    """
)

# Mirrors _spawn_daemon's shape: a launcher that detaches a long-lived child and exits.
LAUNCHER_SOURCE = textwrap.dedent(
    """
    import os, subprocess, sys, textwrap
    marker = sys.argv[1]
    child = textwrap.dedent('''
        import sys, time, pathlib
        time.sleep(2.5)
        pathlib.Path(sys.argv[1]).write_text("alive")
    ''')
    kwargs = {}
    if os.name == "nt":
        kwargs["creationflags"] = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        kwargs["start_new_session"] = True
    subprocess.Popen([sys.executable, "-c", child, marker],
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                     stderr=subprocess.DEVNULL, **kwargs)
    sys.exit(0)
    """
)


def report(label: str, value: object) -> None:
    print(f"[transport-spike] {label}: {value}", flush=True)


class TransportSpike(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.tmp = tempfile.mkdtemp(prefix="transport-spike-")
        cls.client_script = Path(cls.tmp) / "spike_client.py"
        cls.client_script.write_text(CLIENT_SOURCE)
        cls.launcher_script = Path(cls.tmp) / "spike_launcher.py"
        cls.launcher_script.write_text(LAUNCHER_SOURCE)
        report("platform", f"{sys.platform} os.name={os.name} python={sys.version.split()[0]}")
        report("socket.AF_UNIX present", hasattr(socket, "AF_UNIX"))
        report("mpc.families", mpc.families)

    def test_1_a_family_exists_for_this_platform(self):
        expected = "AF_PIPE" if os.name == "nt" else "AF_UNIX"
        report("expected family", expected)
        self.assertIn(
            expected, mpc.families,
            f"{expected} is missing, so multiprocessing.connection cannot carry the daemon here",
        )

    def test_2_two_processes_round_trip(self):
        key = b"spike-key-0123456789"
        listener = mpc.Listener(authkey=key)
        report("listener.address", listener.address)
        report("listener family looks like", "AF_PIPE" if str(listener.address).startswith("\\\\") else "AF_UNIX")
        try:
            proc = subprocess.Popen(
                [sys.executable, str(self.client_script), str(listener.address), key.hex(), "ping"],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            )
            conn = listener.accept()
            try:
                received = conn.recv_bytes()
                conn.send_bytes(received.upper())
            finally:
                conn.close()
            _, err = proc.communicate(timeout=30)
            report("client exit", proc.returncode)
            self.assertEqual(0, proc.returncode, f"client failed: {err.strip()}")
        finally:
            listener.close()

    def test_3_several_clients_at_once(self):
        # The pool's whole purpose. If a Listener can only hold one client at a time on
        # Windows, this transport is the wrong choice regardless of anything else.
        key = b"spike-key-0123456789"
        wanted = 4
        listener = mpc.Listener(authkey=key, backlog=wanted)
        try:
            procs = [
                subprocess.Popen(
                    [sys.executable, str(self.client_script), str(listener.address), key.hex(), f"n{i}"],
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                )
                for i in range(wanted)
            ]
            held = []
            try:
                for _ in range(wanted):
                    held.append(listener.accept())          # all open simultaneously
                report("concurrent connections accepted", len(held))
                for conn in held:
                    conn.send_bytes(conn.recv_bytes().upper())
            finally:
                for conn in held:
                    conn.close()
            codes = []
            for proc in procs:
                _, err = proc.communicate(timeout=30)
                codes.append(proc.returncode)
                if proc.returncode != 0:
                    report("failing client stderr", err.strip())
            report("client exits", codes)
            self.assertEqual([0] * wanted, codes)
        finally:
            listener.close()

    def test_4_a_detached_child_outlives_its_parent(self):
        marker = Path(self.tmp) / "detached.marker"
        launcher = subprocess.run(
            [sys.executable, str(self.launcher_script), str(marker)],
            capture_output=True, text=True, timeout=30,
        )
        report("launcher exit", launcher.returncode)
        self.assertEqual(0, launcher.returncode, launcher.stderr.strip())
        # The launcher is gone; the grandchild writes only after a delay, so a marker
        # appearing now proves it survived its parent.
        deadline = time.time() + 20
        while time.time() < deadline and not marker.exists():
            time.sleep(0.25)
        report("detached child survived", marker.exists())
        self.assertTrue(marker.exists(), "the detached child died with its parent")


if __name__ == "__main__":
    unittest.main()
