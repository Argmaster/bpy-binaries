"""Main entry point script for managing building related actions within this repo."""
from __future__ import annotations

import datetime
import logging
import os
import shutil
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory

import click
import tzlocal
from packaging.version import Version

SCRIPTS_DIRECTORY = Path(__file__).parent


@click.group()
def main() -> None:
    """Root group."""


@main.command()
@click.option(
    "-b",
    "--blender",
    help="Blender version to target.",
    type=Version,
    required=True,
)
@click.option(
    "-p",
    "--python",
    help="Python version to target.",
    type=Version,
    required=True,
    multiple=True,
)
def build(blender: Version, python: list[Version]) -> None:
    """Build Blender as Python module."""
    invocation_directory = Path.cwd()

    logger = logging.getLogger()
    logger.setLevel(logging.DEBUG)
    logger.handlers.clear()

    start_time = datetime.datetime.now(tz=tzlocal.get_localzone())
    time_now_isoformat = start_time.isoformat()
    log_directory = invocation_directory / "log" / "build"
    log_directory.mkdir(mode=0o777, parents=True, exist_ok=True)

    log_file_path = log_directory / f"{time_now_isoformat}.log"
    file_handler = logging.FileHandler(log_file_path.as_posix(), encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    logger.addHandler(file_handler)

    python_version, *_ = python
    process_name = create_process_name(blender, python_version)

    temporary_directory = TemporaryDirectory(suffix=process_name)
    work_path = Path(temporary_directory.name)

    run_command(
        ["git", "clone", "https://github.com/blender/blender"],
        work_dir=work_path,
    )

    blender_directory = work_path / "blender"

    lib_directory = work_path / "lib"
    lib_directory.mkdir(mode=0o777, parents=True, exist_ok=True)

    build_linux_bpy = work_path / "build_linux_bpy"
    build_linux_bpy.mkdir(mode=0o777, parents=True, exist_ok=True)

    run_command(
        [
            "svn",
            "checkout",
            "https://svn.blender.org/svnroot/bf-blender/trunk/lib/linux_x86_64_glibc_228",
        ],
        work_dir=lib_directory,
    )

    # ; python_lib_dir = lib_directory / "linux_x86_64_glibc_228" / "python"
    # ; shutil.copy(f"/bin/python{python_version}", (python_lib_dir / "bin").as_posix())
    # ; shutil.copy(f"/usr/include/python{python_version}",
    # (python_lib_dir / "include").as_posix())

    run_command(["git", "checkout", f"v{blender}"], work_dir=blender_directory)
    run_command(["make", "update"], work_dir=blender_directory)

    run_command(
        ["cmake", f"-DPYTHON_VERSION={python_version}", blender_directory.as_posix()],
        work_dir=build_linux_bpy,
    )

    run_command(["make", "bpy"], work_dir=blender_directory)

    build_output = build_linux_bpy / "bin" / "bpy"
    build_destination = invocation_directory / "dist"
    build_destination.mkdir(mode=0o777, parents=True, exist_ok=True)

    shutil.copytree(build_output.as_posix(), (build_destination / "bpy").as_posix())
    end_time = datetime.datetime.now(tz=tzlocal.get_localzone())
    elapsed_time = end_time - start_time

    logging.info("Elapsed time %.2f", elapsed_time.total_seconds() / 60)


def create_process_name(blender: Version, python: Version) -> str:
    """Create process name including blender version and python version."""
    return f"blender-git-{blender}-{python}"


def run_command(
    args: list[str],
    *,
    work_dir: Path,
    expect_code: int = 0,
) -> subprocess.CompletedProcess[bytes]:
    """Run command in subprocess."""
    begin_dir = Path.cwd()
    os.chdir(work_dir.as_posix())

    try:
        finished_process = subprocess.run(
            args,
            capture_output=True,
            shell=False,
        )
        logging.warning(finished_process.stderr.decode("utf-8"))
        logging.info(finished_process.stdout.decode("utf-8"))

        if finished_process.returncode != expect_code:
            raise UnexpectedReturnCodeError(finished_process.returncode)
    finally:
        os.chdir(begin_dir.as_posix())

    return finished_process


class UnexpectedReturnCodeError(ValueError):
    """Raised when process returns unexpected return code."""
