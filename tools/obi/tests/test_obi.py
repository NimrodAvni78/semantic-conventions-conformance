# Copyright The OpenTelemetry Authors
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

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
    exit_status,
    install,
    main,
    render_config,
    run,
    version,
)

ENDPOINT = "http://127.0.0.1:4317"

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
    if mode == "slow":
        time.sleep(0.5)
    open("attached", "w").write(pid)
    print({attached!r}.format(pid=pid), flush=True)
    print({done!r}, flush=True)
    if mode == "die-later":
        sys.exit(4)
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
    while True:
        time.sleep(0.05)
    """
).format(attached=ATTACHED, done=DONE)


GATED = textwrap.dedent(
    """\
    import os, pathlib, socket, sys
    gate = socket.socket(socket.AF_UNIX)
    gate.connect(os.environ["OTEL_CONFORMANCE_GATE"])
    gate.sendall(f"{os.getpid()}\\n".encode())
    released = gate.recv(1)
    attached = pathlib.Path("attached")
    instrumented = attached.exists() and attached.read_text() == str(os.getpid())
    sys.exit(int(sys.argv[1]) if released and instrumented else 99)
    """
)


def gated(status: int = 0) -> list[str]:
    return [sys.executable, "-c", GATED, str(status)]


def shell(command: list[str]) -> str:
    return " ".join(f"'{part}'" for part in command)


linux_only = pytest.mark.skipif(
    not sys.platform.startswith("linux"), reason="OBI runs on Linux only"
)


def rendered(pid: int = 4242, **environ: str) -> dict:
    environ.setdefault("OTEL_EXPORTER_OTLP_ENDPOINT", ENDPOINT)
    return yaml.safe_load(
        render_config(config_template({}).read_text(), pid, environ)
    )


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


class TestTheExitStatus:
    @pytest.mark.parametrize(("code", "status"), [(0, 0), (3, 3), (-15, 143)])
    def test_a_signal_maps_to_its_shell_status(
        self, code: int, status: int
    ) -> None:
        assert exit_status(code) == status


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
        assert run(gated(3), environ=environ) == 3
        pid = (tmp_path / "attached").read_text()
        assert (tmp_path / "output" / "obi" / f"{pid}.log").is_file()

    def test_the_scenario_is_released_only_once_obi_attached_it(
        self, environ: dict[str, str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("FAKE_OBI_MODE", "slow")

        assert run(gated(), environ=environ) == 0

    def test_a_wrapper_leaves_the_pid_to_the_process_it_starts(
        self, environ: dict[str, str]
    ) -> None:
        command = ["/bin/sh", "-c", shell(gated()) + "; exit $?"]

        assert run(command, environ=environ) == 0

    def test_obi_exiting_before_it_is_ready_fails(
        self, environ: dict[str, str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("FAKE_OBI_MODE", "die-early")

        with pytest.raises(LauncherError, match="before instrumenting"):
            run(gated(), environ=environ)

    def test_obi_exiting_while_the_scenario_runs_fails(
        self, environ: dict[str, str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("FAKE_OBI_MODE", "die-later")

        with pytest.raises(LauncherError, match="while the scenario ran"):
            run(gated(), environ=environ)

    def test_a_scenario_that_exits_before_the_gate_fails(
        self, environ: dict[str, str]
    ) -> None:
        with pytest.raises(LauncherError, match="status 5 before reaching"):
            run([sys.executable, "-c", "raise SystemExit(5)"], environ=environ)

    def test_a_scenario_that_never_reaches_the_gate_fails(
        self, environ: dict[str, str]
    ) -> None:
        environ[READY_TIMEOUT_VARIABLE] = "0.5"

        with pytest.raises(LauncherError, match="did not reach the gate"):
            run(
                [sys.executable, "-c", "import time; time.sleep(30)"],
                environ=environ,
            )

    def test_a_command_that_cannot_start_says_so(
        self,
        environ: dict[str, str],
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        for name, value in environ.items():
            monkeypatch.setenv(name, value)

        assert main(["run", str(tmp_path / "missing")]) == 1
        assert "could not be started" in capsys.readouterr().err
