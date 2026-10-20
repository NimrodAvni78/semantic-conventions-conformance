// Copyright The OpenTelemetry Authors
// SPDX-License-Identifier: Apache-2.0

"use strict";

/**
 * The express server scenario with no OpenTelemetry in the process, for OBI
 * to instrument from outside.
 */

require("@otel-conformance/express-scenarios")
  .serve()
  .catch((error) => {
    console.error(error);
    process.exitCode = 1;
  });
