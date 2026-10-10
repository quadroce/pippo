import subprocess
import sys

import pytest

from pippo import cli


def test_cli_module_imports_and_parses():
    # A syntax error in cli.py once shipped because no test imported it.
    with pytest.raises(SystemExit) as e:
        cli.main(["--version"])
    assert e.value.code == 0


@pytest.mark.parametrize("sub", ["doctor", "heartbeat", "serve", "discover", "images", "channel", "run"])
def test_every_subcommand_is_registered(sub):
    out = subprocess.run([sys.executable, "-m", "pippo", sub, "--help"], capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stderr
    assert "usage" in out.stdout.lower()
