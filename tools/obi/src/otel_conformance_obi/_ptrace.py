# Copyright The OpenTelemetry Authors
# SPDX-License-Identifier: Apache-2.0

"""Holds a scenario's target process at its first network socket.

Every language launcher in this repository is a wrapper that starts the real
runtime as a child, so the process OBI must select does not exist when the run
command starts. The tracer follows forks, clones and execs from the root
command down and marks the command itself, or with a matcher every process
whose new image matches. It holds the first marked process to create an IPv4
or IPv6 socket, from any of its threads:
the runtime and the application are loaded by then, which OBI's runtime
detection and route harvesting need, and no traffic can have been sent yet.
A Go binary is held at its exec instead: OBI hooks Go function entries, and a
Go client's first socket is created inside the request it would miss, while a
static Go binary needs nothing loaded at runtime for OBI to recognize it.
A seccomp filter installed before the first exec makes that syscall the only
one that stops a thread.
"""

from __future__ import annotations

import ctypes
import fnmatch
import functools
import mmap
import os
import platform
import signal
import time
from pathlib import Path
from typing import Callable, Sequence

PTRACE_TRACEME = 0
PTRACE_CONT = 7
PTRACE_SETOPTIONS = 0x4200
PTRACE_GETEVENTMSG = 0x4201

PTRACE_O_TRACEFORK = 0x2
PTRACE_O_TRACEVFORK = 0x4
PTRACE_O_TRACECLONE = 0x8
PTRACE_O_TRACEEXEC = 0x10
PTRACE_O_TRACESECCOMP = 0x80
PTRACE_O_EXITKILL = 0x100000

PTRACE_EVENT_FORK = 1
PTRACE_EVENT_VFORK = 2
PTRACE_EVENT_CLONE = 3
PTRACE_EVENT_EXEC = 4
PTRACE_EVENT_SECCOMP = 7

WALL = 0x40000000

OPTIONS = (
    PTRACE_O_TRACEFORK
    | PTRACE_O_TRACEVFORK
    | PTRACE_O_TRACECLONE
    | PTRACE_O_TRACEEXEC
    | PTRACE_O_TRACESECCOMP
    | PTRACE_O_EXITKILL
)

SPAWN_EVENTS = (PTRACE_EVENT_FORK, PTRACE_EVENT_VFORK, PTRACE_EVENT_CLONE)

PR_SET_NO_NEW_PRIVS = 38
PR_SET_SECCOMP = 22
SECCOMP_MODE_FILTER = 2
SECCOMP_RET_ALLOW = 0x7FFF0000
SECCOMP_RET_TRACE = 0x7FF00000

AF_INET = 2
AF_INET6 = 10

ARCHITECTURES = {
    "x86_64": (0xC000003E, 41),
    "aarch64": (0xC00000B7, 198),
}

GO_BUILDINFO_MAGIC = b"\xff Go buildinf:"

POLL_INTERVAL = 0.001

DEBUG = os.environ.get("OTEL_CONFORMANCE_OBI_DEBUG")


def _debug(message: str) -> None:
    if DEBUG:
        with open(DEBUG, "a", encoding="utf-8") as log:
            print(f"{time.monotonic():.3f} {os.getpid()} {message}", file=log)


def _image(pid: int) -> str:
    try:
        exe = os.readlink(f"/proc/{pid}/exe")
        argv = (
            Path(f"/proc/{pid}/cmdline")
            .read_bytes()
            .replace(b"\0", b" ")
            .decode(errors="replace")
        )
    except OSError as error:
        return f"<{error.strerror}>"
    return f"{exe} [{argv.strip()}]"


def _tgid(tid: int) -> int:
    try:
        for line in Path(f"/proc/{tid}/status").read_text().splitlines():
            if line.startswith("Tgid:"):
                return int(line.split()[1])
    except OSError:
        pass
    return tid


class TraceError(RuntimeError):
    """The process tree could not be followed."""


class _SockFilter(ctypes.Structure):
    _fields_ = [
        ("code", ctypes.c_ushort),
        ("jt", ctypes.c_ubyte),
        ("jf", ctypes.c_ubyte),
        ("k", ctypes.c_uint),
    ]


class _SockFprog(ctypes.Structure):
    _fields_ = [
        ("len", ctypes.c_ushort),
        ("filter", ctypes.POINTER(_SockFilter)),
    ]


@functools.cache
def _libc() -> ctypes.CDLL:
    libc = ctypes.CDLL(None, use_errno=True)
    libc.ptrace.argtypes = [
        ctypes.c_long,
        ctypes.c_long,
        ctypes.c_void_p,
        ctypes.c_void_p,
    ]
    libc.ptrace.restype = ctypes.c_long
    return libc


def socket_filter(
    machine: str | None = None,
) -> list[tuple[int, int, int, int]]:
    try:
        audit_arch, socket_nr = ARCHITECTURES[machine or platform.machine()]
    except KeyError:
        raise TraceError(
            f"no seccomp filter for {machine or platform.machine()}"
        ) from None
    load, jump, ret = 0x20, 0x15, 0x06
    return [
        (load, 0, 0, 4),
        (jump, 0, 5, audit_arch),
        (load, 0, 0, 0),
        (jump, 0, 3, socket_nr),
        (load, 0, 0, 16),
        (jump, 2, 0, AF_INET),
        (jump, 1, 0, AF_INET6),
        (ret, 0, 0, SECCOMP_RET_ALLOW),
        (ret, 0, 0, SECCOMP_RET_TRACE),
    ]


def _install_socket_filter() -> None:
    program = socket_filter()
    filters = (_SockFilter * len(program))(
        *(_SockFilter(*instruction) for instruction in program)
    )
    fprog = _SockFprog(len(program), filters)
    libc = _libc()
    if libc.prctl(PR_SET_NO_NEW_PRIVS, 1, 0, 0, 0) != 0:
        os._exit(125)
    if (
        libc.prctl(PR_SET_SECCOMP, SECCOMP_MODE_FILTER, ctypes.byref(fprog))
        != 0
    ):
        os._exit(124)


def _ptrace(
    request: int, pid: int, data: int = 0, addr: ctypes.c_void_p | None = None
) -> None:
    if _libc().ptrace(request, pid, addr, ctypes.c_void_p(data)) != 0:
        error = ctypes.get_errno()
        raise TraceError(f"ptrace({request:#x}, {pid}): {os.strerror(error)}")


def _event_message(pid: int) -> int:
    message = ctypes.c_ulong()
    if (
        _libc().ptrace(PTRACE_GETEVENTMSG, pid, None, ctypes.byref(message))
        != 0
    ):
        error = ctypes.get_errno()
        raise TraceError(f"reading the event of {pid}: {os.strerror(error)}")
    return message.value


def image_matcher(
    executable: str | None, argv: str | None
) -> Callable[[int], bool] | None:
    if executable is None and argv is None:
        return None

    def matches(pid: int) -> bool:
        if executable is not None:
            try:
                name = Path(os.readlink(f"/proc/{pid}/exe")).name
            except OSError:
                return False
            if not fnmatch.fnmatchcase(name, executable):
                return False
        if argv is not None:
            try:
                raw = Path(f"/proc/{pid}/cmdline").read_bytes()
            except OSError:
                return False
            line = " ".join(
                part.decode(errors="replace")
                for part in raw.split(b"\0")
                if part
            )
            if not fnmatch.fnmatchcase(line, argv):
                return False
        return True

    return matches


def is_go_executable(path: str) -> bool:
    try:
        with open(path, "rb") as exe:
            with mmap.mmap(exe.fileno(), 0, access=mmap.ACCESS_READ) as image:
                return image.find(GO_BUILDINFO_MAGIC) != -1
    except (OSError, ValueError):
        return False


def is_go_binary(pid: int) -> bool:
    return is_go_executable(f"/proc/{pid}/exe")


def exit_status(status: int) -> int:
    if os.WIFSIGNALED(status):
        return 128 + os.WTERMSIG(status)
    return os.WEXITSTATUS(status)


class Tracer:
    def __init__(
        self, command: Sequence[str], matches: Callable[[int], bool] | None
    ) -> None:
        self._command = list(command)
        self._matches = matches
        self._traced: set[int] = set()
        self._fresh: set[int] = set()
        self._held: set[int] = set()
        self._matched: set[int] = set()
        self._released = False
        self.root = 0
        self.target: int | None = None
        self.status: int | None = None

    def spawn(self) -> int:
        pid = os.fork()
        if pid == 0:
            try:
                _install_socket_filter()
                if _libc().ptrace(PTRACE_TRACEME, 0, None, None) != 0:
                    os._exit(126)
                os.execvp(self._command[0], self._command)
            finally:
                os._exit(127)
        _, status = os.waitpid(pid, WALL)
        if not os.WIFSTOPPED(status):
            raise TraceError(
                f"{self._command[0]} could not be started (status {exit_status(status)})"
            )
        self.root = pid
        self._traced.add(pid)
        _ptrace(PTRACE_SETOPTIONS, pid, OPTIONS)
        _debug(f"spawned {pid} {_image(pid)}")
        if not self._mark(pid):
            _ptrace(PTRACE_CONT, pid)
        return pid

    def _mark(self, pid: int) -> bool:
        matched = (
            pid == self.root if self._matches is None else self._matches(pid)
        )
        if not matched:
            self._matched.discard(pid)
            return False
        if self.target is None and is_go_binary(pid):
            _debug(f"{pid} held at exec: a Go binary")
            self.target = pid
            self._held.add(pid)
            return True
        self._matched.add(pid)
        return False

    def find_target(self, timeout: float) -> int:
        deadline = time.monotonic() + timeout
        while self.target is None:
            if self.status is not None:
                raise TraceError(
                    "the scenario exited before the process to instrument opened a socket"
                    if self._matched
                    else "the scenario exited before the process to instrument started"
                )
            if time.monotonic() > deadline:
                raise TraceError(
                    f"no process matching the target opened a socket within {timeout:g}s"
                )
            self.service()
        return self.target

    def release(self) -> None:
        self._released = True
        for held in sorted(self._held):
            _debug(f"{held} released")
            _ptrace(PTRACE_CONT, held)
        self._held.clear()

    def signal_root(self, signum: int) -> None:
        if self.root > 0 and self.status is None:
            os.kill(self.root, signum)

    def kill(self) -> None:
        if self.root <= 0:
            return
        for pid in (*self._traced, self.root):
            try:
                os.kill(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        while self.status is None:
            self.service()

    def wait(self) -> int:
        while self.status is None:
            self.service()
        return self.status

    def service(self) -> None:
        progressed = False
        for pid in sorted({*self._traced, self.root}):
            if pid == self.root and self.status is not None:
                continue
            try:
                waited, status = os.waitpid(pid, os.WNOHANG | WALL)
            except ChildProcessError:
                self._traced.discard(pid)
                continue
            if waited == 0:
                continue
            progressed = True
            self._handle(pid, status)
        if not progressed:
            time.sleep(POLL_INTERVAL)

    def _handle(self, pid: int, status: int) -> None:
        if os.WIFEXITED(status) or os.WIFSIGNALED(status):
            self._traced.discard(pid)
            self._fresh.discard(pid)
            self._held.discard(pid)
            if pid == self.root:
                _debug(f"{pid} exited {exit_status(status)}")
                self.status = exit_status(status)
            return
        if not os.WIFSTOPPED(status):
            return
        stop = os.WSTOPSIG(status)
        event = status >> 16
        if event in SPAWN_EVENTS:
            child = _event_message(pid)
            self._traced.add(child)
            self._fresh.add(child)
            _ptrace(PTRACE_CONT, pid)
        elif event == PTRACE_EVENT_EXEC:
            _debug(f"{pid} exec {_image(pid)}")
            if not self._mark(pid):
                _ptrace(PTRACE_CONT, pid)
        elif event == PTRACE_EVENT_SECCOMP:
            tgid = _tgid(pid)
            if (
                not self._released
                and tgid in self._matched
                and self.target in (None, tgid)
            ):
                _debug(f"{pid} of {tgid} held at its first socket")
                self._held.add(pid)
                self.target = tgid
            else:
                _ptrace(PTRACE_CONT, pid)
        elif stop == signal.SIGSTOP and pid in self._fresh:
            self._fresh.discard(pid)
            _ptrace(PTRACE_CONT, pid)
        elif stop == signal.SIGTRAP:
            _ptrace(PTRACE_CONT, pid)
        else:
            _ptrace(PTRACE_CONT, pid, stop)
