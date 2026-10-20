// Copyright The OpenTelemetry Authors
// SPDX-License-Identifier: Apache-2.0

"use strict";

/**
 * The undici client scenario with no OpenTelemetry in the process, for OBI
 * to instrument from outside.
 */

require("@otel-conformance/undici-scenarios")
  .drivePackagedContract()
  .catch((error) => {
    console.error(error);
    process.exitCode = 1;
  });
