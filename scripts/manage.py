#!/usr/bin/env python
"""Main entry point script for managing building related actions within this repo."""
from __future__ import annotations

import datetime
import logging
import os
import shutil
import subprocess
from concurrent.futures import Future, ProcessPoolExecutor
from pathlib import Path
from tempfile import TemporaryDirectory

import click
import jinja2
import tzlocal
from packaging.version import Version

SCRIPTS_DIRECTORY = Path(__file__).parent
PYPROJECT_BUILD = """[build-system]
requires = ["setuptools", "wheel"]
build-backend = "setuptools.build_meta"

[bdist_wheel]
universal = 0
"""


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
    with ProcessPoolExecutor() as executor:
        tasks: list[Future[None]] = []

        for python_version in python:
            task = executor.submit(_build, blender, python_version)
            tasks.append(task)

        for i, (task, python_version) in enumerate(zip(tasks, python)):
            try:
                task.result()
            except Exception:
                logging.exception(
                    "Task %d Blender %s Python %s failed.",
                    i,
                    str(blender),
                    str(python_version),
                )
            else:
                logging.info(
                    "Task %d Blender %s Python %s succeeded.",
                    i,
                    str(blender),
                    str(python_version),
                )


def _build(blender: Version, python_version: Version) -> None:
    invocation_directory = Path.cwd()

    configure_logger(blender, python_version)

    start_time = datetime.datetime.now(tz=tzlocal.get_localzone())

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

    shutil.copytree(
        build_output.as_posix(),
        (build_destination / f"bpy_{blender}_{python_version}").as_posix(),
    )
    end_time = datetime.datetime.now(tz=tzlocal.get_localzone())
    elapsed_time = end_time - start_time

    logging.info("Elapsed time %.2f", elapsed_time.total_seconds() / 60)


def configure_logger(blender: Version, python_version: Version) -> None:
    """Configure logger."""
    logger = logging.getLogger()
    logger.setLevel(logging.DEBUG)
    logger.handlers.clear()

    start_time = datetime.datetime.now(tz=tzlocal.get_localzone())
    time_now_isoformat = start_time.isoformat()
    log_directory = Path.cwd() / "log" / "build"
    log_directory.mkdir(mode=0o777, parents=True, exist_ok=True)

    log_file_path = (
        log_directory / f"{time_now_isoformat}_{blender}_{python_version}.log"
    )
    file_handler = logging.FileHandler(log_file_path.as_posix(), encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    logger.addHandler(file_handler)

    stream_handler = logging.StreamHandler()
    stream_handler.setLevel(logging.WARNING)
    logger.addHandler(stream_handler)


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
        logging.debug(finished_process.stderr.decode("utf-8"))
        logging.debug(finished_process.stdout.decode("utf-8"))

        if finished_process.returncode != expect_code:
            raise UnexpectedReturnCodeError(finished_process.returncode)
    finally:
        os.chdir(begin_dir.as_posix())

    return finished_process


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
@click.option(
    "-s",
    "--system",
    help="System wheel tag.",
    type=str,
    required=True,
)
def package(blender: Version, python: list[Version], system: str) -> None:
    """Create package with blender bpy binaries as wheel."""
    for python_version in python:
        _package(blender, python_version, system)


def _package(blender: Version, python_version: Version, system: str) -> None:
    configure_logger(blender, python_version)

    environment = jinja2.Environment(
        loader=jinja2.FileSystemLoader(SCRIPTS_DIRECTORY / "templates"),
        autoescape=jinja2.select_autoescape(),
    )
    template = environment.get_template("setup.jinja2-py")
    content = template.render(blender_version=blender, python_version=python_version)

    with TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)

        shutil.copy(Path.cwd() / "README.md", temp_path / "README.md")
        shutil.copy(Path.cwd() / "COPYING", temp_path / "COPYING")
        shutil.copytree(
            Path.cwd() / "dist" / f"bpy_{blender}_{python_version}",
            temp_path / "bpy",
        )

        (temp_path / "setup.py").write_text(content)
        (temp_path / "pyproject.toml").write_text(PYPROJECT_BUILD)

        py_tag = f"{python_version.major}{python_version.minor}"
        run_command(
            [
                "python",
                "-m",
                "setup",
                "bdist_wheel",
                "--plat-name",
                system,
                "--python-tag",
                f"cp{py_tag}",
                "--py-limited-api",
                f"cp{py_tag}",
                "--dist-dir",
                (Path.cwd() / "dist").as_posix(),
            ],
            work_dir=temp_path,
        )


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
@click.option(
    "-s",
    "--system",
    help="System wheel tag.",
    type=str,
    required=True,
)
def test(blender: Version, python: list[Version], system: str) -> None:
    """Test wheel with blender bpy binaries."""
    for python_version in python:
        _test(blender, python_version, system)


def _test(blender: Version, python_version: Version, system: str) -> None:
    configure_logger(blender, python_version)

    py_tag = f"py{python_version.major}{python_version.minor}"
    cp_tag = f"cp{python_version.major}{python_version.minor}"

    try:
        run_command(
            [
                "tox",
                "-e",
                py_tag,
                "--",
                f"bpy-{blender}-{cp_tag}-none-{system}.whl",
            ],
            work_dir=Path.cwd(),
        )
    except UnexpectedReturnCodeError as e:
        logging.exception(
            "Testing Blender %s Python %s System %s finished with code %d",
            str(blender),
            str(python_version),
            system,
            e.args[0],
        )
    else:
        logging.warning(
            "Testing Blender %s Python %s System %s finished with code 0",
            str(blender),
            str(python_version),
            system,
        )


class UnexpectedReturnCodeError(ValueError):
    """Raised when process returns unexpected return code."""
