# OBI conformance scenarios

[OpenTelemetry eBPF Instrumentation (OBI)](https://github.com/open-telemetry/opentelemetry-ebpf-instrumentation)
instruments a process from outside it, so an OBI directory runs the same
uninstrumented workload as every other implementation of its library, with
no SDK and no agent in the process, and wraps the run command instead:

```yaml
instrumentation_library: go.opentelemetry.io/obi
setup: otel-conformance-obi install -- otel-conformance-go build
scenarios:
  server:
    run: otel-http-drive --serve otel-conformance-obi run build/scenario
```

A directory is `<library>/obi/<side>/`, beside the library's other
implementations, so the report compares OBI with them library by library.

## `otel-conformance-obi`

`install [-- COMMAND...]` downloads the release pinned in
[`versions.env`](src/otel_conformance_obi/versions.env) into
`~/.cache/otel-conformance/obi/<version>/`, then runs `COMMAND`, which is the
directory's own build step: `setup:` is one command.

`run COMMAND...` runs a scenario:

1. Starts `COMMAND` with `OTEL_CONFORMANCE_GATE` naming a Unix socket the
   launcher listens on.
2. Waits for the scenario to reach the gate: before its workload, the
   scenario connects, sends its own PID and blocks. The PID comes from the
   process that will make the requests, so a wrapper in between (`uv run`,
   `gradle run`) needs no special handling. In Go the gate is
   [`scenario.WaitAtGate`](../go/scenario).
3. Starts OBI with [`obi.yaml`](src/otel_conformance_obi/obi.yaml) selecting
   only that PID, and releases the scenario once OBI logs that it attached
   the process and registered its PID, so the first request is measured.
4. After `COMMAND` exits, keeps OBI running for the settle period, longer than
   both the span batch delay and the metric export interval, then stops it.
   OBI does not export what it still buffers when it is stopped.

The gate exists because OBI finds new processes by polling `/proc` and then
attaches from user space, which takes about a second, while a scenario's whole
workload can finish in less than 100 ms. Starting OBI first and selecting the
scenario by executable path measures nothing.

`run` exits with `COMMAND`'s status. It fails instead when the scenario exits
before or never reaches the gate, when OBI exits before it is stopped, or when
the scenario exits before OBI attached to it, so a missing signal in the
report is never a crashed agent.

OBI needs root and a Linux kernel with BTF. The launcher runs it with
`sudo -n` when it is not root, which the GitHub-hosted runners allow.

## Configuration

[`obi.yaml`](src/otel_conformance_obi/obi.yaml) is an OBI Config v2 document.
`run` substitutes `${OBI_TARGET_PID}`, `${OTEL_EXPORTER_OTLP_ENDPOINT}` and
`${OBI_METRIC_EXPORT_INTERVAL}` and passes the result to `obi -config`. It
selects every attribute OBI can emit (`attributes.select: {"*": {include:
["*"]}}`) and every HTTP payload extractor with 64 KiB capture buffers, so a
run measures the most OBI can say, not its default subset.

`wakeup_len: 0` makes the kernel wake OBI's ring-buffer reader on every event.
Any other value sizes the wakeup threshold by the Go tracer's event, which the
generic tracer's smaller HTTP event never reaches, so a single request is only
read by a fallback poll every 3 s, and OBI drops what is still in the ring
buffer when it stops.

A replacement template must keep `log_level: debug`: readiness is read from
OBI's debug log, and `run` refuses a template without it.

| Variable | |
| --- | --- |
| `OTEL_CONFORMANCE_OBI_BINARY` | an OBI binary to use instead of the pinned release |
| `OTEL_CONFORMANCE_OBI_CONFIG` | another config template, for example one adding `daemon.logging.debug_trace_output: text` |
| `OTEL_CONFORMANCE_OBI_READY_TIMEOUT` | seconds to wait for the scenario to reach the gate, and again for OBI to attach to it (60) |
| `OTEL_CONFORMANCE_OBI_SETTLE` | seconds OBI keeps running after `COMMAND` exits (3) |

OBI's own log for a run lands in `output/obi/<pid>.log` in the scenario
directory.
