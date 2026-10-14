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


def test_run_overrides_apply_to_one_run_without_touching_the_config():
    from pippo.config import Settings

    base = Settings(api_base_url="https://x.test", agent_api_key="k", parallelism=4, observation_window_sec=60)
    assert cli.with_overrides(base, 2, None).parallelism == 2
    assert cli.with_overrides(base, None, 30).observation_window_sec == 30
    both = cli.with_overrides(base, 2, 45)
    assert (both.parallelism, both.observation_window_sec) == (2, 45) and base.parallelism == 4
    assert cli.with_overrides(base, None, None) is base
    assert cli.with_overrides(base, 0, -5) is base                         # nonsense values are ignored


def test_run_command_accepts_the_new_flags():
    out = subprocess.run([sys.executable, "-m", "pippo", "run", "--help"], capture_output=True, text=True, timeout=60)
    assert "--parallelism" in out.stdout and "--window" in out.stdout
