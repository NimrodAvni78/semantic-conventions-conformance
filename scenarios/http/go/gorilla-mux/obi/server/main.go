// Copyright The OpenTelemetry Authors
// SPDX-License-Identifier: Apache-2.0

// Command server runs the gorilla-mux server scenario with no in-process
// instrumentation, for OBI to instrument from outside.
package main

import (
	"log"
	"os"

	muxscenarios "github.com/open-telemetry/semantic-conventions-conformance/scenarios/http/go/gorilla-mux/scenarios"
	"github.com/open-telemetry/semantic-conventions-conformance/tools/go/scenario"
)

func main() {
	stopping := make(chan error, 1)
	go func() { stopping <- scenario.WaitForEOF(os.Stdin) }()
	if err := muxscenarios.RunServer(nil, stopping); err != nil {
		log.Fatal(err)
	}
}
