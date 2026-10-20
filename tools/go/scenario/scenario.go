// Copyright The OpenTelemetry Authors
// SPDX-License-Identifier: Apache-2.0

// Package scenario is what a Go scenario needs before any telemetry: what the
// runner told it, and how it learns the runner is finished with it.
//
// It carries no OpenTelemetry dependency at all, which is the point. A
// scenario measuring an out-of-process agent must be able to reach the runner
// and the shutdown protocol without linking an SDK it never asked for, so
// these live apart from [scenariosdk]. Nothing here is specific to a domain.
package scenario

import (
	"fmt"
	"io"
	"net"
	"os"
)

// GateVariable names the Unix socket a scenario waits at before its workload.
const GateVariable = "OTEL_CONFORMANCE_GATE"

// Require returns the environment variable named by name or an error.
func Require(name string) (string, error) {
	value := os.Getenv(name)
	if value == "" {
		return "", fmt.Errorf("required environment variable is missing: %s", name)
	}
	return value, nil
}

// WaitForEOF blocks until input closes.
//
// A closed pipe rather than a signal: it means the same thing on every
// platform, and returning is what gives an SDK the chance to flush, so a
// scenario that exits any other way reports less than it produced. The
// protocol is the same in every domain.
func WaitForEOF(input io.Reader) error {
	if _, err := io.Copy(io.Discard, input); err != nil {
		return fmt.Errorf("reading stop input: %w", err)
	}
	return nil
}

// WaitAtGate sends this process's PID to the socket named by [GateVariable]
// and blocks until the launcher listening there releases it. It returns at
// once when the variable is unset.
func WaitAtGate() error {
	path := os.Getenv(GateVariable)
	if path == "" {
		return nil
	}
	gate, err := net.Dial("unix", path)
	if err != nil {
		return fmt.Errorf("reaching the gate: %w", err)
	}
	defer gate.Close()
	if _, err := fmt.Fprintf(gate, "%d\n", os.Getpid()); err != nil {
		return fmt.Errorf("reporting to the gate: %w", err)
	}
	var release [1]byte
	if _, err := io.ReadFull(gate, release[:]); err != nil {
		return fmt.Errorf("waiting at the gate: %w", err)
	}
	return nil
}
