# Copyright The OpenTelemetry Authors
# SPDX-License-Identifier: Apache-2.0

"""``otel-conformance-obi``: runs a scenario under OpenTelemetry eBPF
Instrumentation.

OBI instruments a process from outside it, so the scenario program carries no
OpenTelemetry at all and the run command wraps it instead of preloading an
agent into it. Two subcommands:

``install [-- COMMAND...]``
    What a package's ``setup:`` runs. Downloads the pinned OBI release into
    the cache, then runs ``COMMAND`` — the scenario's own build step — so a
    single ``setup:`` covers both.

``run [--target GLOB] [--argv GLOB] COMMAND...``
    What a scenario's ``run:`` runs. Starts ``COMMAND`` and follows its
    process tree to the process to instrument: ``COMMAND`` itself, or with
    ``--target``/``--argv`` the first process whose executable name and
    command line match. Holds that process at its first IPv4/IPv6 socket (a
    Go binary at its exec), starts OBI selecting only it, resumes it once OBI
    reports it instrumented, keeps OBI running for a settle period after
    ``COMMAND`` exits so its exporters flush, then stops it. Exits with
    ``COMMAND``'s status, or fails when OBI exits before it is stopped.
"""

from __future__ import annotations

import argparse
import os
import platform
import re
import shutil
import signal
import subprocess
import sys
import tarfile
import tempfile
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import IO, Mapping, Sequence

from ._ptrace import TraceError, Tracer, image_matcher

INSTALL = "install"

RUN = "run"

BINARY = "obi"

RELEASES = (
    "https://github.com/open-telemetry/opentelemetry-ebpf-instrumentation"
    "/releases/download"
)

BINARY_VARIABLE = "OTEL_CONFORMANCE_OBI_BINARY"

READY_TIMEOUT_VARIABLE = "OTEL_CONFORMANCE_OBI_READY_TIMEOUT"

SETTLE_VARIABLE = "OTEL_CONFORMANCE_OBI_SETTLE"

CONFIG_VARIABLE = "OTEL_CONFORMANCE_OBI_CONFIG"

CONFIG = "obi.yaml"

DEFAULT_READY_TIMEOUT = 60.0

METRIC_EXPORT_INTERVAL_MILLIS = 1000

DEFAULT_SETTLE = 3.0

STOP_TIMEOUT = 30.0

LOG_DIR = Path("output") / "obi"

ATTACHED_MESSAGE = "new executable for discovered process"

DONE_MESSAGE = "msg=.done"

ATTACHER_COMPONENT = "component=discover.traceAttacher"

DEBUG_LOG_LEVEL = re.compile(r"^log_level:\s*debug\s*$", re.MULTILINE)

ARCHITECTURES = {
    "x86_64": "amd64",
    "amd64": "amd64",
    "aarch64": "arm64",
    "arm64": "arm64",
}


class LauncherError(RuntimeError):
    """OBI could not be installed, started, or attached."""


def version() -> str:
    pins = Path(__file__).with_name("versions.env").read_text(encoding="utf-8")
    match = re.search(r"^OBI_VERSION=(\S+)$", pins, re.MULTILINE)
    if match is None:
        raise LauncherError("versions.env pins no OBI_VERSION")
    return match.group(1)


def architecture(machine: str | None = None) -> str:
    machine = (machine or platform.machine()).lower()
    try:
        return ARCHITECTURES[machine]
    except KeyError:
        raise LauncherError(f"OBI publishes no build for {machine}") from None


def archive_url(release: str, arch: str) -> str:
    return f"{RELEASES}/{release}/obi-{release}-linux-{arch}.tar.gz"


def cache_dir(release: str, environ: Mapping[str, str] = os.environ) -> Path:
    root = environ.get("XDG_CACHE_HOME") or str(Path.home() / ".cache")
    return Path(root) / "otel-conformance" / "obi" / release


def binary(environ: Mapping[str, str] = os.environ) -> Path:
    override = environ.get(BINARY_VARIABLE)
    if override:
        return Path(override)
    return cache_dir(version(), environ) / BINARY


def install(environ: Mapping[str, str] = os.environ) -> Path:
    if environ.get(BINARY_VARIABLE):
        return binary(environ)
    release = version()
    target = cache_dir(release, environ) / BINARY
    if target.is_file():
        return target
    target.parent.mkdir(parents=True, exist_ok=True)
    url = archive_url(release, architecture())
    print(f"downloading {url}", file=sys.stderr, flush=True)
    with tempfile.TemporaryDirectory(dir=target.parent) as scratch:
        archive = Path(scratch) / "obi.tar.gz"
        staged = Path(scratch) / BINARY
        try:
            with (
                urllib.request.urlopen(url) as response,  # noqa: S310
                archive.open("wb") as out,
            ):
                shutil.copyfileobj(response, out)
            with tarfile.open(archive) as bundle:
                source = bundle.extractfile(bundle.getmember(BINARY))
                if source is None:
                    raise KeyError(BINARY)
                with source, staged.open("wb") as out:
                    shutil.copyfileobj(source, out)
        except (urllib.error.URLError, OSError) as error:
            raise LauncherError(f"downloading {url}: {error}") from error
        except (tarfile.TarError, KeyError) as error:
            raise LauncherError(
                f"{url} holds no {BINARY} executable: {error}"
            ) from error
        staged.chmod(0o755)
        staged.replace(target)
    return target


def config_template(environ: Mapping[str, str] = os.environ) -> Path:
    override = environ.get(CONFIG_VARIABLE)
    return Path(override) if override else Path(__file__).with_name(CONFIG)


def render_config(template: str, pid: int, environ: Mapping[str, str]) -> str:
    endpoint = environ.get("OTEL_EXPORTER_OTLP_ENDPOINT")
    if not endpoint:
        raise LauncherError("OTEL_EXPORTER_OTLP_ENDPOINT is not set")
    protocol = environ.get("OTEL_EXPORTER_OTLP_PROTOCOL", "grpc")
    if protocol != "grpc":
        raise LauncherError(f"OBI scenarios export over grpc, not {protocol}")
    if not DEBUG_LOG_LEVEL.search(template):
        raise LauncherError(
            f"{CONFIG} must set `log_level: debug`: the launcher resumes the "
            "scenario on OBI's debug log of the attach"
        )
    values = {
        "OBI_TARGET_PID": str(pid),
        "OTEL_EXPORTER_OTLP_ENDPOINT": endpoint,
        "OBI_METRIC_EXPORT_INTERVAL": str(METRIC_EXPORT_INTERVAL_MILLIS),
    }

    def substitute(match: re.Match[str]) -> str:
        name = match.group(1)
        if name not in values:
            raise LauncherError(f"{CONFIG} references unknown variable {name}")
        return values[name]

    return re.sub(r"\$\{([A-Z0-9_]+)\}", substitute, template)


class Readiness:
    def __init__(self, pid: int) -> None:
        self._pid = re.compile(rf"\bpid={pid}\b")
        self._attached = False

    def feed(self, line: str) -> bool:
        if not self._attached:
            self._attached = (
                ATTACHED_MESSAGE in line and self._pid.search(line) is not None
            )
            return False
        return DONE_MESSAGE in line and ATTACHER_COMPONENT in line


def obi_command(executable: Path, config: Path) -> list[str]:
    command = [str(executable), "-config", str(config)]
    if os.geteuid() != 0:
        command = ["sudo", "-n", *command]
    return command


class _Follower(threading.Thread):
    def __init__(self, stream: IO[bytes], log: IO[bytes], pid: int) -> None:
        super().__init__(daemon=True)
        self._stream = stream
        self._log = log
        self._readiness = Readiness(pid)
        self.ready = threading.Event()

    def run(self) -> None:
        for raw in iter(self._stream.readline, b""):
            self._log.write(raw)
            self._log.flush()
            if not self.ready.is_set() and self._readiness.feed(
                raw.decode(errors="replace")
            ):
                self.ready.set()


def _wait_ready(
    obi: subprocess.Popen[bytes],
    follower: _Follower,
    tracer: Tracer,
    timeout: float,
) -> None:
    deadline = time.monotonic() + timeout
    while not follower.ready.is_set():
        tracer.service()
        if obi.poll() is not None:
            raise LauncherError(
                f"OBI exited with status {obi.returncode} before instrumenting"
            )
        if tracer.status is not None:
            raise LauncherError(
                f"the scenario exited with status {tracer.status} before OBI "
                "instrumented it"
            )
        if time.monotonic() > deadline:
            raise LauncherError(
                f"OBI did not instrument the scenario within {timeout:g}s"
            )


def _stop(obi: subprocess.Popen[bytes]) -> None:
    if obi.poll() is not None:
        return
    obi.send_signal(signal.SIGTERM)
    try:
        obi.wait(STOP_TIMEOUT)
    except subprocess.TimeoutExpired:
        obi.kill()
        obi.wait()


def _tail(path: Path, lines: int = 40) -> str:
    try:
        return "".join(
            path.read_text(errors="replace").splitlines(keepends=True)[-lines:]
        )
    except OSError:
        return ""


def run(
    command: Sequence[str],
    target: str | None = None,
    argv: str | None = None,
    environ: Mapping[str, str] = os.environ,
) -> int:
    if not sys.platform.startswith("linux"):
        raise LauncherError("OBI runs on Linux only")
    if not command:
        raise LauncherError("run needs the scenario command")
    executable = binary(environ)
    if not executable.is_file():
        raise LauncherError(
            f"{executable} is missing — `otel-conformance-obi install` fetches it"
        )
    ready_timeout = float(
        environ.get(READY_TIMEOUT_VARIABLE, DEFAULT_READY_TIMEOUT)
    )
    settle = float(environ.get(SETTLE_VARIABLE, DEFAULT_SETTLE))
    template = config_template(environ).read_text(encoding="utf-8")

    tracer = Tracer(command, image_matcher(target, argv))
    for forwarded in (signal.SIGINT, signal.SIGTERM):
        signal.signal(
            forwarded, lambda signum, _frame: tracer.signal_root(signum)
        )
    obi: subprocess.Popen[bytes] | None = None
    log_path: Path | None = None
    try:
        tracer.spawn()
        pid = tracer.find_target(ready_timeout)
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        log_path = (LOG_DIR / f"{pid}.log").resolve()
        with (
            tempfile.TemporaryDirectory() as scratch,
            log_path.open("wb") as log,
        ):
            config = Path(scratch) / "obi.yaml"
            config.write_text(
                render_config(template, pid, environ), encoding="utf-8"
            )
            obi = subprocess.Popen(  # noqa: S603
                obi_command(executable, config),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
            )
            assert obi.stdout is not None
            follower = _Follower(obi.stdout, log, pid)
            follower.start()
            _wait_ready(obi, follower, tracer, ready_timeout)
            tracer.release()
            status = tracer.wait()
            deadline = time.monotonic() + settle
            while time.monotonic() < deadline and obi.poll() is None:
                time.sleep(0.05)
            if obi.poll() is not None:
                raise LauncherError(
                    f"OBI exited with status {obi.returncode} while the "
                    "scenario ran"
                )
            _stop(obi)
            follower.join(STOP_TIMEOUT)
        return status
    except BaseException as error:
        tracer.kill()
        if obi is not None:
            _stop(obi)
        if log_path is not None:
            print(_tail(log_path), file=sys.stderr)
        if isinstance(error, TraceError):
            raise LauncherError(str(error)) from error
        raise


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="otel-conformance-obi",
        description=(__doc__ or "").splitlines()[0],
    )
    commands = parser.add_subparsers(dest="action", required=True)
    install_parser = commands.add_parser(
        INSTALL, help="fetch the pinned OBI release, then run COMMAND"
    )
    install_parser.add_argument("command", nargs=argparse.REMAINDER)
    run_parser = commands.add_parser(RUN, help="run COMMAND under OBI")
    run_parser.add_argument(
        "--target",
        help="glob on the executable name of the process to instrument",
    )
    run_parser.add_argument(
        "--argv", help="glob on the command line of the process to instrument"
    )
    run_parser.add_argument("command", nargs=argparse.REMAINDER)
    return parser


def _strip_separator(command: Sequence[str]) -> list[str]:
    command = list(command)
    return command[1:] if command[:1] == ["--"] else command


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    command = _strip_separator(arguments.command)
    try:
        if arguments.action == INSTALL:
            install()
            if not command:
                return 0
            try:
                return subprocess.call(command)  # noqa: S603
            except OSError as error:
                raise LauncherError(f"{command[0]}: {error}") from error
        return run(command, arguments.target, arguments.argv)
    except LauncherError as error:
        print(f"otel-conformance-obi: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
