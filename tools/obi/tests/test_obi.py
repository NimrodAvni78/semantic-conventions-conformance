# Copyright The OpenTelemetry Authors
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import os
import subprocess
import sys
import textwrap
import urllib.error
from pathlib import Path

import pytest
import yaml

import otel_conformance_obi
from otel_conformance_obi import (
    BINARY_VARIABLE,
    CONFIG_VARIABLE,
    METRIC_EXPORT_INTERVAL_MILLIS,
    READY_TIMEOUT_VARIABLE,
    SETTLE_VARIABLE,
    LauncherError,
    Readiness,
    architecture,
    archive_url,
    binary,
    cache_dir,
    config_template,
    install,
    main,
    render_config,
    run,
    version,
)
from otel_conformance_obi._ptrace import (
    AF_INET,
    AF_INET6,
    ARCHITECTURES,
    SECCOMP_RET_ALLOW,
    SECCOMP_RET_TRACE,
    Tracer,
    image_matcher,
    is_go_executable,
    socket_filter,
)

ENDPOINT = "http://127.0.0.1:4317"

PYTHON = Path(os.path.realpath(sys.executable)).name

SOCKET = "import socket; socket.socket().close()"

ATTACHED = 'level=DEBUG msg="new executable for discovered process" component=discover.traceAttacher pid={pid} child=[]'

DONE = "level=DEBUG msg=.done component=discover.traceAttacher"

FAKE_OBI = textwrap.dedent(
    """\
    import os, re, signal, sys, time
    config = open(sys.argv[sys.argv.index("-config") + 1]).read()
    pid = re.search(r"target_pids: \\[(\\d+)\\]", config).group(1)
    mode = os.environ.get("FAKE_OBI_MODE", "ready")
    if mode == "die-early":
        sys.exit(3)
    print({attached!r}.format(pid=pid), flush=True)
    print({done!r}, flush=True)
    if mode == "die-later":
        sys.exit(4)
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
    while True:
        time.sleep(0.05)
    """
).format(attached=ATTACHED, done=DONE)


def opens_socket(marker: str = "", status: int = 0) -> list[str]:
    program = SOCKET + (f"; raise SystemExit({status})" if status else "")
    return [sys.executable, "-c", program, *([marker] if marker else [])]


def shell(command: list[str]) -> str:
    return " ".join(f"'{part}'" for part in command)


def socket_count(pid: int) -> int:
    return sum(
        1
        for fd in Path(f"/proc/{pid}/fd").iterdir()
        if os.readlink(fd).startswith("socket:")
    )


linux_only = pytest.mark.skipif(
    not sys.platform.startswith("linux"), reason="ptrace is Linux only"
)


def rendered(pid: int = 4242, **environ: str) -> dict:
    environ.setdefault("OTEL_EXPORTER_OTLP_ENDPOINT", ENDPOINT)
    return yaml.safe_load(
        render_config(config_template({}).read_text(), pid, environ)
    )


def run_bpf(
    program: list[tuple[int, int, int, int]], data: dict[int, int]
) -> int:
    accumulator = 0
    pc = 0
    while True:
        code, jt, jf, k = program[pc]
        if code == 0x20:
            accumulator = data[k]
            pc += 1
        elif code == 0x15:
            pc += 1 + (jt if accumulator == k else jf)
        elif code == 0x06:
            return k
        else:
            raise AssertionError(f"unexpected BPF opcode {code:#x}")


class TestTheRelease:
    def test_the_version_is_pinned(self) -> None:
        assert version().startswith("v")

    @pytest.mark.parametrize(
        ("machine", "arch"),
        [("x86_64", "amd64"), ("aarch64", "arm64"), ("arm64", "arm64")],
    )
    def test_the_machine_names_an_archive(
        self, machine: str, arch: str
    ) -> None:
        assert architecture(machine) == arch
        assert archive_url("v1.2.3", arch).endswith(
            "/v1.2.3/obi-v1.2.3-linux-" + arch + ".tar.gz"
        )

    def test_an_unsupported_machine_says_so(self) -> None:
        with pytest.raises(LauncherError, match="no build for riscv64"):
            architecture("riscv64")

    def test_the_binary_is_cached_per_version(self, tmp_path: Path) -> None:
        environ = {"XDG_CACHE_HOME": str(tmp_path)}

        assert (
            binary(environ)
            == tmp_path / "otel-conformance" / "obi" / version() / "obi"
        )
        assert (
            cache_dir("v9", environ)
            == tmp_path / "otel-conformance" / "obi" / "v9"
        )

    def test_an_explicit_binary_wins(self, tmp_path: Path) -> None:
        assert (
            binary({BINARY_VARIABLE: str(tmp_path / "obi")})
            == tmp_path / "obi"
        )

    def test_install_with_an_explicit_binary_runs_the_command(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setenv(BINARY_VARIABLE, str(tmp_path / "obi"))
        marker = tmp_path / "ran"

        status = main(
            [
                "install",
                "--",
                sys.executable,
                "-c",
                f"open({str(marker)!r}, 'w').close()",
            ]
        )

        assert status == 0
        assert marker.exists()

    def test_a_missing_setup_command_says_so(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        monkeypatch.setenv(BINARY_VARIABLE, str(tmp_path / "obi"))

        assert main(["install", "--", str(tmp_path / "missing")]) == 1
        assert "missing" in capsys.readouterr().err

    def test_a_failed_download_says_so(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        def refuse(url: str) -> None:
            raise urllib.error.URLError("no route")

        monkeypatch.setattr(
            otel_conformance_obi.urllib.request, "urlopen", refuse
        )

        with pytest.raises(LauncherError, match="no route"):
            install({"XDG_CACHE_HOME": str(tmp_path)})


class TestTheConfig:
    def test_it_is_config_v2(self) -> None:
        config = rendered()

        assert config["file_format"] == "1.0"
        assert config["extensions"]["obi"]["version"] == "2.0"

    def test_it_selects_only_the_scenario_process(self) -> None:
        capture = rendered(pid=31337)["extensions"]["obi"]["capture"]

        assert capture["policy"]["default_action"] == "exclude"
        assert [
            rule["match"]["process"]["target_pids"]
            for rule in capture["rules"]
        ] == [[31337]]

    def test_it_exports_to_the_runner(self) -> None:
        config = rendered()

        traces = config["tracer_provider"]["processors"][0]["batch"]
        metrics = config["meter_provider"]["readers"][0]["periodic"]
        assert traces["exporter"]["otlp_grpc"]["endpoint"] == ENDPOINT
        assert metrics["exporter"]["otlp_grpc"]["endpoint"] == ENDPOINT
        assert metrics["interval"] == METRIC_EXPORT_INTERVAL_MILLIS

    def test_both_exports_fit_in_the_settle_period(self) -> None:
        config = rendered()

        schedule = config["tracer_provider"]["processors"][0]["batch"][
            "schedule_delay"
        ]
        interval = config["meter_provider"]["readers"][0]["periodic"][
            "interval"
        ]
        settle = otel_conformance_obi.DEFAULT_SETTLE * 1000
        assert max(schedule, interval) < settle

    def test_every_attribute_is_selected(self) -> None:
        select = rendered()["extensions"]["obi"]["enrich"]["attributes"][
            "select"
        ]

        assert select == {"*": {"include": ["*"]}}

    def test_a_missing_endpoint_says_so(self) -> None:
        with pytest.raises(LauncherError, match="OTEL_EXPORTER_OTLP_ENDPOINT"):
            render_config("log_level: debug\n", 1, {})

    def test_only_grpc_is_exported(self) -> None:
        with pytest.raises(LauncherError, match="http/protobuf"):
            rendered(OTEL_EXPORTER_OTLP_PROTOCOL="http/protobuf")

    def test_an_unknown_reference_says_so(self) -> None:
        with pytest.raises(LauncherError, match="NOPE"):
            render_config(
                "log_level: debug\nx: ${NOPE}",
                1,
                {"OTEL_EXPORTER_OTLP_ENDPOINT": ENDPOINT},
            )

    def test_a_template_without_debug_logging_says_so(self) -> None:
        with pytest.raises(LauncherError, match="log_level: debug"):
            render_config(
                "log_level: info\n",
                1,
                {"OTEL_EXPORTER_OTLP_ENDPOINT": ENDPOINT},
            )

    def test_another_template_can_be_chosen(self, tmp_path: Path) -> None:
        other = tmp_path / "obi.yaml"

        assert config_template({CONFIG_VARIABLE: str(other)}) == other


class TestReadiness:
    def test_ready_once_the_attach_of_the_pid_is_done(self) -> None:
        readiness = Readiness(42)

        assert not readiness.feed(ATTACHED.format(pid=42))
        assert readiness.feed(DONE)

    def test_done_before_the_attach_is_not_ready(self) -> None:
        readiness = Readiness(42)

        assert not readiness.feed(DONE)
        assert not readiness.feed(
            'level=INFO msg="instrumenting process" pid=42'
        )

    def test_another_pid_is_not(self) -> None:
        readiness = Readiness(42)

        assert not readiness.feed(ATTACHED.format(pid=421))
        assert not readiness.feed(DONE)


@linux_only
class TestFollowingTheProcessTree:
    def test_the_command_itself_is_the_default_target(self) -> None:
        tracer = Tracer(opens_socket(), image_matcher(None, None))
        root = tracer.spawn()

        assert tracer.find_target(10) == root
        assert socket_count(root) == 0
        tracer.release()
        assert tracer.wait() == 0

    def test_without_a_target_a_child_is_never_selected(self) -> None:
        tracer = Tracer(
            ["/bin/sh", "-c", shell(opens_socket()) + "; exit 0"],
            image_matcher(None, None),
        )
        tracer.spawn()

        with pytest.raises(
            otel_conformance_obi.TraceError, match="opened a socket"
        ):
            tracer.find_target(10)

    def test_a_target_started_by_a_wrapper_is_held_at_its_socket(
        self,
    ) -> None:
        tracer = Tracer(
            ["/bin/sh", "-c", "/bin/true && exec " + shell(opens_socket())],
            image_matcher(PYTHON, None),
        )
        root = tracer.spawn()

        target = tracer.find_target(10)

        assert target == root
        assert Path(os.readlink(f"/proc/{target}/exe")).name == PYTHON
        tracer.release()
        assert tracer.wait() == 0

    def test_a_forked_target_is_found(self) -> None:
        tracer = Tracer(
            ["/bin/sh", "-c", shell(opens_socket()) + "; exit 3"],
            image_matcher(PYTHON, None),
        )
        root = tracer.spawn()

        target = tracer.find_target(10)

        assert target != root
        tracer.release()
        assert tracer.wait() == 3

    def test_a_command_line_glob_narrows_the_target(self) -> None:
        tracer = Tracer(
            [
                "/bin/sh",
                "-c",
                shell(opens_socket("first"))
                + "; "
                + shell(opens_socket("second")),
            ],
            image_matcher(PYTHON, "* second"),
        )
        tracer.spawn()

        target = tracer.find_target(10)

        assert (
            Path(f"/proc/{target}/cmdline").read_bytes().split(b"\0")[-2]
            == b"second"
        )
        tracer.release()
        assert tracer.wait() == 0

    def test_a_matching_process_that_opens_no_socket_is_skipped(
        self,
    ) -> None:
        probe = shell([sys.executable, "-c", "pass"])
        tracer = Tracer(
            ["/bin/sh", "-c", probe + "; " + shell(opens_socket("second"))],
            image_matcher(PYTHON, None),
        )
        tracer.spawn()

        target = tracer.find_target(10)

        assert (
            Path(f"/proc/{target}/cmdline").read_bytes().split(b"\0")[-2]
            == b"second"
        )
        tracer.release()
        assert tracer.wait() == 0

    def test_unix_sockets_do_not_hold_the_target(self) -> None:
        program = "import socket; socket.socket(socket.AF_UNIX).close()"
        tracer = Tracer(
            [sys.executable, "-c", program + "; " + SOCKET],
            image_matcher(None, None),
        )
        tracer.spawn()

        tracer.find_target(10)
        tracer.release()
        assert tracer.wait() == 0

    def test_a_scenario_that_never_starts_the_target_fails(self) -> None:
        tracer = Tracer(["/bin/true"], image_matcher("never-*", None))
        tracer.spawn()

        with pytest.raises(
            otel_conformance_obi.TraceError, match="exited before"
        ):
            tracer.find_target(10)

    def test_a_target_that_opens_no_socket_fails(self) -> None:
        tracer = Tracer(["/bin/true"], image_matcher(None, None))
        tracer.spawn()

        with pytest.raises(
            otel_conformance_obi.TraceError, match="opened a socket"
        ):
            tracer.find_target(10)

    def test_a_command_that_cannot_start_fails(self, tmp_path: Path) -> None:
        tracer = Tracer([str(tmp_path / "missing")], image_matcher(None, None))

        with pytest.raises(
            otel_conformance_obi.TraceError, match="could not be started"
        ):
            tracer.spawn()


class TestSignallingBeforeTheRootExists:
    def test_kill_signals_nothing(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        signalled: list[tuple[int, int]] = []
        monkeypatch.setattr(
            otel_conformance_obi._ptrace.os,
            "kill",
            lambda pid, signum: signalled.append((pid, signum)),
        )
        tracer = Tracer(["true"], image_matcher(None, None))

        tracer.kill()
        tracer.signal_root(15)

        assert signalled == []


@linux_only
class TestRunningUnderOBI:
    @pytest.fixture
    def environ(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> dict[str, str]:
        fake = tmp_path / "fake-obi"
        fake.write_text(f"#!{sys.executable}\n{FAKE_OBI}")
        fake.chmod(0o755)
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr(
            otel_conformance_obi,
            "obi_command",
            lambda executable, config: [
                str(executable),
                "-config",
                str(config),
            ],
        )
        return {
            BINARY_VARIABLE: str(fake),
            "OTEL_EXPORTER_OTLP_ENDPOINT": ENDPOINT,
            SETTLE_VARIABLE: "0.2",
            READY_TIMEOUT_VARIABLE: "20",
        }

    def test_the_scenario_status_is_returned(
        self, environ: dict[str, str], tmp_path: Path
    ) -> None:
        assert run(opens_socket(status=3), environ=environ) == 3
        assert any((tmp_path / "output" / "obi").glob("*.log"))

    def test_obi_exiting_before_it_is_ready_fails(
        self, environ: dict[str, str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("FAKE_OBI_MODE", "die-early")

        with pytest.raises(LauncherError, match="before instrumenting"):
            run(opens_socket(), environ=environ)

    def test_obi_exiting_while_the_scenario_runs_fails(
        self, environ: dict[str, str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("FAKE_OBI_MODE", "die-later")
        program = SOCKET + "; import time; time.sleep(1)"

        with pytest.raises(LauncherError, match="while the scenario ran"):
            run([sys.executable, "-c", program], environ=environ)

    def test_a_command_that_cannot_start_leaves_the_caller_alone(
        self, environ: dict[str, str], tmp_path: Path
    ) -> None:
        launcher = subprocess.run(
            [
                sys.executable,
                "-c",
                "import sys; from otel_conformance_obi import main; "
                f"sys.exit(main(['run', {str(tmp_path / 'missing')!r}]))",
            ],
            env={**os.environ, **environ},
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
            start_new_session=True,
        )

        assert launcher.returncode == 1
        assert "could not be started" in launcher.stderr


class TestTheSocketFilter:
    @pytest.mark.parametrize("machine", sorted(ARCHITECTURES))
    def test_it_traces_only_inet_sockets(self, machine: str) -> None:
        program = socket_filter(machine)
        audit_arch, socket_nr = ARCHITECTURES[machine]

        def verdict(arch: int, nr: int, domain: int) -> int:
            return run_bpf(program, {4: arch, 0: nr, 16: domain})

        assert verdict(audit_arch, socket_nr, AF_INET) == SECCOMP_RET_TRACE
        assert verdict(audit_arch, socket_nr, AF_INET6) == SECCOMP_RET_TRACE
        assert verdict(audit_arch, socket_nr, 1) == SECCOMP_RET_ALLOW
        assert verdict(audit_arch, socket_nr + 1, AF_INET) == SECCOMP_RET_ALLOW
        assert verdict(0x40000003, socket_nr, AF_INET) == SECCOMP_RET_ALLOW

    def test_an_unknown_machine_says_so(self) -> None:
        with pytest.raises(otel_conformance_obi.TraceError, match="riscv64"):
            socket_filter("riscv64")


class TestRecognizingGoBinaries:
    def test_the_build_info_marks_a_go_binary(self, tmp_path: Path) -> None:
        binary = tmp_path / "server"
        binary.write_bytes(
            b"\x7fELF" + b"\0" * 64 + b"\xff Go buildinf:" + b"\0" * 16
        )

        assert is_go_executable(str(binary))

    def test_another_executable_is_not(self) -> None:
        assert not is_go_executable(sys.executable)

    def test_an_empty_or_missing_file_is_not(self, tmp_path: Path) -> None:
        empty = tmp_path / "empty"
        empty.write_bytes(b"")

        assert not is_go_executable(str(empty))
        assert not is_go_executable(str(tmp_path / "missing"))
