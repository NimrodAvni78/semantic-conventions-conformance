# Copyright The OpenTelemetry Authors
# SPDX-License-Identifier: Apache-2.0

"""The shared pyramid server workload with no in-process instrumentation,
for OBI to instrument from outside."""

from __future__ import annotations

import sys
from pathlib import Path

from otel_conformance_obi.scenario import wait_at_gate
from otel_http_test_client import serve

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scenarios"))

from server import create_config  # noqa: E402

wait_at_gate()
serve(lambda: create_config().make_wsgi_app())
