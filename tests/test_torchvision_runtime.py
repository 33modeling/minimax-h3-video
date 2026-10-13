"""Native torchvision failure, safe repair, and server startup regressions."""

import importlib.util
import json
import os
import subprocess
import zipfile
from pathlib import Path
from unittest import mock

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "check_torchvision", ROOT / "scripts/check_torchvision.py"
)
runtime = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runtime)


def result(code=0, out="", err=""):
    return subprocess.CompletedProcess([], code, out, err)


def wheel(path, version="0.26.0+cu130", dependency="torch==2.11.0"):
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(
            "torchvision-0.26.0.dist-info/METADATA",
            f"Name: torchvision\nVersion: {version}\nRequires-Dist: {dependency}\n",
        )


@pytest.mark.parametrize(
    ("cuda", "flavor"), [("13.0", "cu130"), ("12.6", "cu126"), (None, "cpu")]
)
def test_source_matches_installed_runtime(cuda, flavor):
    assert runtime.wheel_source({"version": "2.11.0", "cuda": cuda}) == (
        flavor,
        "torchvision>=0.26,<0.27",
    )


@pytest.mark.parametrize("version", ["2.11.0.dev20260101", "1.13.1", "2.99.0"])
def test_unverified_releases_do_not_guess(version):
    with pytest.raises(RuntimeError):
        runtime.wheel_source({"version": version, "cuda": "13.0"})


def test_healthy_runtime_never_installs():
    with (
        mock.patch.object(runtime, "run_probe", return_value=result(out="NMS OK\n")),
        mock.patch.object(runtime, "repair") as repair,
    ):
        assert runtime.main(["--repair"]) == 0
        repair.assert_not_called()


def test_check_is_read_only(capsys):
    with (
        mock.patch.object(
            runtime,
            "run_probe",
            return_value=result(1, err="operator torchvision::nms does not exist\n"),
        ),
        mock.patch.object(runtime, "repair") as repair,
    ):
        assert runtime.main([]) == 1
        repair.assert_not_called()
    assert "torchvision::nms" in capsys.readouterr().err


def test_driver_failure_does_not_reinstall_torchvision():
    error = subprocess.CalledProcessError(1, [], stderr="driver too old")
    with (
        mock.patch.object(runtime, "run_probe", return_value=result(1)),
        mock.patch.object(runtime.subprocess, "run", side_effect=error),
        mock.patch.object(runtime, "repair") as repair,
    ):
        assert runtime.main(["--repair"]) == 1
        repair.assert_not_called()


@pytest.mark.parametrize("final_code", [0, 1])
def test_repair_is_rechecked_in_fresh_process(final_code):
    info = {"version": "2.11.0+cu130", "cuda": "13.0"}
    with (
        mock.patch.object(
            runtime, "run_probe", side_effect=[result(1), result(final_code)]
        ) as probe,
        mock.patch.object(
            runtime.subprocess, "run", return_value=result(out=json.dumps(info))
        ),
        mock.patch.object(runtime, "repair") as repair,
    ):
        assert runtime.main(["--repair"]) == final_code
        assert probe.call_count == 2
        repair.assert_called_once_with(info)


@pytest.mark.parametrize(
    ("version", "dependency", "valid"),
    [
        ("0.26.0+cu130", "torch==2.11.0", True),
        ("0.26.0+cpu", "torch==2.11.0", False),
        ("0.26.0+cu128", "torch==2.11.0", False),
        ("0.25.0+cu130", "torch==2.10.0", False),
        ("0.26.0+cu130", "numpy", False),
    ],
)
def test_wheel_metadata_is_checked_before_install(tmp_path, version, dependency, valid):
    path = tmp_path / "torchvision.whl"
    wheel(path, version, dependency)
    if valid:
        runtime.verify_wheel(path, "2.11.0+cu130", "cu130")
    else:
        with pytest.raises(RuntimeError):
            runtime.verify_wheel(path, "2.11.0+cu130", "cu130")


def test_repair_keeps_torch_and_selects_exact_cuda_wheel(tmp_path):
    commands = []

    def pip(*args):
        commands.append(args)
        if "--report" in args:
            Path(args[args.index("--report") + 1]).write_text(
                json.dumps(
                    {
                        "install": [
                            {
                                "metadata": {
                                    "name": "torchvision",
                                    "version": "0.26.0+cpu",
                                }
                            }
                        ],
                    }
                )
            )
        if "--dest" in args:
            wheel(Path(args[args.index("--dest") + 1]) / "torchvision-test.whl")

    with (
        mock.patch.object(runtime.sys, "prefix", str(tmp_path)),
        mock.patch.object(runtime, "pip_command", side_effect=pip),
    ):
        runtime.repair({"version": "2.11.0+cu130", "cuda": "13.0"})
    assert "torch==2.11.0+cu130" in commands[0]
    assert "torchvision==0.26.0+cu130" in commands[1]
    assert "--no-deps" in commands[1] and "--no-deps" in commands[2]
    assert "--force-reinstall" in commands[2]


def test_resolver_torch_replacement_is_rejected(tmp_path):
    def pip(*args):
        Path(args[args.index("--report") + 1]).write_text(
            json.dumps(
                {
                    "install": [{"metadata": {"name": "torch", "version": "2.12.0"}}],
                }
            )
        )

    with (
        mock.patch.object(runtime.sys, "prefix", str(tmp_path)),
        mock.patch.object(runtime, "pip_command", side_effect=pip) as command,
    ):
        with pytest.raises(RuntimeError, match="replace torch"):
            runtime.repair({"version": "2.11.0+cu130", "cuda": "13.0"})
        assert command.call_count == 1


def test_system_python_is_not_modified():
    with (
        mock.patch.object(runtime.sys, "prefix", runtime.sys.base_prefix),
        mock.patch.object(runtime, "pip_command") as command,
    ):
        with pytest.raises(RuntimeError, match="system Python"):
            runtime.repair({"version": "2.11.0", "cuda": "13.0"})
        command.assert_not_called()


def test_inherited_cpu_index_cannot_override_repair():
    env = {
        "PIP_EXTRA_INDEX_URL": "https://example.invalid/cpu",
        "PIP_INDEX_URL": "https://example.invalid/cpu",
        "PIP_NO_INDEX": "1",
        "PIP_TARGET": "/wrong/site-packages",
    }
    with (
        mock.patch.dict(os.environ, env),
        mock.patch.object(runtime.subprocess, "run") as run,
    ):
        runtime.pip_command(
            "download", "--index-url", "https://download.pytorch.org/whl/cu130"
        )
    passed = run.call_args.kwargs["env"]
    assert passed["PIP_CONFIG_FILE"] == os.devnull
    assert all(key not in passed for key in env)


def test_probe_reproduces_missing_operator_in_real_child(tmp_path):
    (tmp_path / "torch.py").write_text("")
    (tmp_path / "torchvision.py").write_text(
        "raise RuntimeError('operator torchvision::nms does not exist')\n"
    )
    with mock.patch.dict(os.environ, {"PYTHONPATH": str(tmp_path)}):
        failed = runtime.run_probe(False)
    assert failed.returncode != 0
    assert "operator torchvision::nms does not exist" in failed.stderr


@pytest.mark.parametrize(
    "script",
    ["serve.sh", "up.sh", "provision.sh", "fix_torch_cuda.sh", "fix_torchvision.sh"],
)
def test_launch_scripts_parse_with_bash(script):
    subprocess.run(["bash", "-n", str(ROOT / "scripts" / script)], check=True)


def test_direct_server_stops_before_launch_on_failed_nms(tmp_path):
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    (scripts / "serve.sh").write_bytes((ROOT / "scripts/serve.sh").read_bytes())
    model = tmp_path / "model"
    model.mkdir()
    (model / "model_index.json").write_text("{}")
    bin_dir = tmp_path / "venv" / "bin"
    bin_dir.mkdir(parents=True)
    python = bin_dir / "python"
    python.write_text(
        '#!/bin/sh\necho "operator torchvision::nms does not exist" >&2\nexit 1\n'
    )
    python.chmod(0o755)
    sglang = bin_dir / "sglang"
    sglang.write_text(f'#!/bin/sh\ntouch "{tmp_path / "launched"}"\n')
    sglang.chmod(0o755)
    (scripts / "cluster_env.sh").write_text(
        f'export VENV="{bin_dir.parent}" H3_MODEL_DIR="{model}" H3_PORT_FL2VA=30010 H3_NUM_GPUS=1 H3_ENGINE=sglang\n'
        f'export PATH="{bin_dir}:$PATH"\n'
        'h3_cuda_compat() { return 0; }\n'
    )
    failed = subprocess.run(
        ["bash", str(scripts / "serve.sh"), "fl2va"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert failed.returncode == 1
    assert "torchvision::nms" in failed.stderr
    assert not (tmp_path / "launched").exists()
