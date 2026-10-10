"""Check real torchvision kernels; repair torchvision without replacing torch."""

import argparse
import email
import fcntl
import json
import os
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

try:
    from packaging.requirements import Requirement
    from packaging.version import Version
except ImportError:
    from pip._vendor.packaging.requirements import Requirement
    from pip._vendor.packaging.version import Version


PROBE = """
import sys, torch, torchvision
from torchvision.ops import nms
for device in (('cpu', 'cuda') if sys.argv[1] == 'gpu' else ('cpu',)):
    boxes = torch.tensor([[0., 0., 1., 1.], [0., 0., 1., 1.]], device=device)
    scores = torch.tensor([0.9, 0.8], device=device)
    assert nms(boxes, scores, 0.5).tolist() == [0], 'NMS returned incorrect indices'
print('torch', torch.__version__, 'torchvision', torchvision.__version__, 'NMS OK')
"""
TORCH_INFO = """
import json, sys, torch
if sys.argv[1] == 'gpu':
    torch.zeros(1, device='cuda')
print(json.dumps({'version': torch.__version__, 'cuda': torch.version.cuda,
                 'hip': torch.version.hip}))
"""


def run_probe(gpu):
    # A fresh process is essential after a failed torchvision import.
    return subprocess.run(
        [sys.executable, "-c", PROBE, "gpu" if gpu else "cpu"],
        capture_output=True,
        text=True,
        check=False,
    )


def wheel_source(info):
    version = Version(info["version"])
    # Official compatibility table: https://github.com/pytorch/vision#installation
    if (
        version.is_prerelease
        or version.release[0] != 2
        or not 0 <= version.release[1] <= 13
    ):
        raise RuntimeError(
            f"Unsupported torch release: {version}; install its matching torchvision explicitly"
        )
    if info.get("hip"):
        raise RuntimeError("Automatic repair supports CPU/CUDA builds, not ROCm")
    flavor = "cu" + info["cuda"].replace(".", "") if info["cuda"] else "cpu"
    minor = version.release[1] + 15
    return flavor, f"torchvision>=0.{minor},<0.{minor + 1}"


def pip_command(*args):
    # Keep inherited extra indexes from selecting a CPU/different-CUDA wheel.
    env = dict(os.environ)
    for key in (
        "PIP_INDEX_URL",
        "PIP_EXTRA_INDEX_URL",
        "PIP_FIND_LINKS",
        "PIP_NO_INDEX",
        "PIP_CONSTRAINT",
        "PIP_REQUIREMENT",
        "PIP_TARGET",
        "PIP_PREFIX",
        "PIP_USER",
    ):
        env.pop(key, None)
    env["PIP_CONFIG_FILE"] = os.devnull
    subprocess.run(
        [sys.executable, "-m", "pip", "--disable-pip-version-check", *args],
        env=env,
        check=True,
    )


def verify_wheel(path, torch_version, flavor):
    with zipfile.ZipFile(path) as archive:
        metadata = [
            name for name in archive.namelist() if name.endswith(".dist-info/METADATA")
        ]
        if len(metadata) != 1:
            raise RuntimeError("Invalid torchvision wheel metadata")
        message = email.message_from_bytes(archive.read(metadata[0]))
    if (
        message["Name"].lower() != "torchvision"
        or Version(message["Version"]).local != flavor
    ):
        raise RuntimeError(f"Torchvision wheel does not match the {flavor} runtime")
    requirements = [Requirement(item) for item in message.get_all("Requires-Dist", [])]
    torch_requirements = [
        item
        for item in requirements
        if item.name.lower() == "torch"
        and (item.marker is None or item.marker.evaluate())
    ]
    if not torch_requirements or any(
        not item.specifier.contains(torch_version) for item in torch_requirements
    ):
        raise RuntimeError(
            f"Torchvision wheel does not support installed torch {torch_version}"
        )


def repair(info):
    if sys.prefix == sys.base_prefix:
        raise RuntimeError(
            "Refusing to modify system Python; run this in the project venv"
        )
    # Multiple nodes share this venv. Never let pip uninstall it concurrently.
    with (Path(sys.prefix) / ".torchvision-repair.lock").open("a") as lease:
        fcntl.flock(lease, fcntl.LOCK_EX)
        repair_wheel(info)


def repair_wheel(info):
    flavor, requirement = wheel_source(info)
    index = f"https://download.pytorch.org/whl/{flavor}"
    with tempfile.TemporaryDirectory(prefix="h3-torchvision-") as directory:
        directory = Path(directory)
        report = directory / "plan.json"
        # Resolve against the exact installed torch. Do not reinstall/upgrade it.
        pip_command(
            "install",
            "--dry-run",
            "--upgrade",
            "--only-binary=:all:",
            "--index-url",
            index,
            "--report",
            str(report),
            f"torch=={info['version']}",
            requirement,
        )
        plan = json.loads(report.read_text())["install"]
        for item in plan:
            if item["metadata"]["name"].lower() == "torch":
                raise RuntimeError(
                    "Resolver would replace torch; refusing automatic repair"
                )
        versions = [
            item["metadata"]["version"]
            for item in plan
            if item["metadata"]["name"].lower() == "torchvision"
        ]
        if versions:
            version = versions[0]
        else:
            # Correct version may still have a damaged native extension.
            from importlib.metadata import version as installed_version

            version = installed_version("torchvision")
        # A CPU wheel can otherwise satisfy a public version constraint.
        target = f"{Version(version).public}+{flavor}"
        pip_command(
            "download",
            "--no-deps",
            "--only-binary=:all:",
            "--index-url",
            index,
            "--dest",
            str(directory),
            f"torchvision=={target}",
        )
        wheels = list(directory.glob("torchvision-*.whl"))
        if len(wheels) != 1:
            raise RuntimeError("Expected one torchvision wheel")
        verify_wheel(wheels[0], info["version"], flavor)
        pip_command("install", "--no-deps", "--force-reinstall", str(wheels[0]))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repair", action="store_true")
    parser.add_argument(
        "--cpu-only", action="store_true", help="Skip GPU checks during provisioning"
    )
    args = parser.parse_args(argv)
    gpu = not args.cpu_only
    result = run_probe(gpu)
    if result.returncode == 0:
        print(result.stdout, end="")
        return 0
    print(result.stderr, file=sys.stderr, end="")
    if not args.repair:
        print("[torchvision] Run: bash scripts/fix_torchvision.sh", file=sys.stderr)
        return 1
    # Driver/torch failures cannot be fixed by reinstalling torchvision.
    try:
        info_result = subprocess.run(
            [sys.executable, "-c", TORCH_INFO, "gpu" if gpu else "cpu"],
            capture_output=True,
            text=True,
            check=True,
        )
        info = json.loads(info_result.stdout)
        print(
            f"[torchvision] Repair for torch {info['version']} CUDA {info['cuda']}",
            flush=True,
        )
        repair(info)
    except (RuntimeError, ValueError, OSError, subprocess.CalledProcessError) as exc:
        print(f"[torchvision] Repair failed: {exc}", file=sys.stderr)
        if isinstance(exc, subprocess.CalledProcessError) and exc.stderr:
            print(exc.stderr, file=sys.stderr, end="")
        return 1
    result = run_probe(gpu)
    if result.returncode:
        print(result.stderr, file=sys.stderr, end="")
        print(
            "[torchvision] NMS check still fails; server will not start",
            file=sys.stderr,
        )
        return 1
    print(result.stdout, end="")
    return 0


if __name__ == "__main__":
    sys.exit(main())
