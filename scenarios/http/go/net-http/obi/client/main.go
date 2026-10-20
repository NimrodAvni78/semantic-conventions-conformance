// Copyright The OpenTelemetry Authors
// SPDX-License-Identifier: Apache-2.0

// Command client runs the net/http client scenario with no in-process
// instrumentation, for OBI to instrument from outside.
package main

import (
	"log"

	"github.com/open-telemetry/semantic-conventions-conformance/scenarios/http/go/net-http/scenarios"
)

func main() {
	if err := scenarios.RunClient(nil); err != nil {
		log.Fatal(err)
	}
}
