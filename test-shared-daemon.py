"""Shared Windows daemon descendants survive frontend family reloads."""
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent / "lib/cly"))
import processes as p


def fixture_birth(pid):
    if os.name != "nt" and sys.platform == "darwin":
        return "Wed Oct 14 12:00:{:02d} 2026".format(pid)
    return str(pid)


original = p._shared_daemon
try:
    p._shared_daemon = lambda item: item.pid == 20
    table = {10: p.ProcessIdentity(10, fixture_birth(10), 1),
             11: p.ProcessIdentity(11, fixture_birth(11), 10),
             20: p.ProcessIdentity(20, fixture_birth(20), 10),
             21: p.ProcessIdentity(21, fixture_birth(21), 20)}
    family = p._family({10: table[10]}, table)
    assert set(family) == {10, 11}, family
    # Shutdown revalidation must use the same exclusion as the initial plan.
    assert set(p._family(family, table)) == {10, 11}
finally:
    p._shared_daemon = original

if os.name == "nt":
    import runtime
    native = runtime.windows_details
    birth = p.birth
    try:
        runtime.windows_details = lambda pid: {"argv": ["C:/bin/codex.exe", "app-server", "--managed-daemon"]}
        p.birth = lambda pid: table[20].birth
        assert p._shared_daemon(table[20])
        p.birth = lambda pid: "999"
        assert not p._shared_daemon(table[20]), "Reused PID must not be excluded"
        p.birth = lambda pid: table[20].birth
        runtime.windows_details = lambda pid: {"argv": ["C:/bin/codex.exe", "exec", "--managed-daemon"]}
        assert not p._shared_daemon(table[20]), "Ordinary tools remain in the reload family"
    finally:
        runtime.windows_details, p.birth = native, birth

print("Shared daemon family checks passed")
