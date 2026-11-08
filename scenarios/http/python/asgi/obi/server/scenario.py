# Copyright The OpenTelemetry Authors
# SPDX-License-Identifier: Apache-2.0

"""The shared asgi server workload with no in-process instrumentation,
for OBI to instrument from outside."""

from __future__ import annotations

import sys
from pathlib import Path

from otel_conformance_obi.scenario import wait_at_gate

python_root = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(python_root / "shared"))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scenarios"))

from asgi_server import serve  # noqa: E402
from server import application  # noqa: E402

wait_at_gate()
serve(lambda: application)
