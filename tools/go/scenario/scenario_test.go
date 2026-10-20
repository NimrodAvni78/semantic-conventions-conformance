// Copyright The OpenTelemetry Authors
// SPDX-License-Identifier: Apache-2.0

package scenario

import (
	"bufio"
	"errors"
	"net"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"testing"
	"testing/iotest"
)

func TestRequire(t *testing.T) {
	const name = "OTEL_CONFORMANCE_TEST_REQUIRED"
	tests := []struct {
		name    string
		value   string
		present bool
		wantErr bool
	}{
		{name: "unset", wantErr: true},
		{name: "empty", present: true, wantErr: true},
		{name: "present", value: "value", present: true},
	}
	for _, test := range tests {
		t.Run(test.name, func(t *testing.T) {
			if test.present {
				t.Setenv(name, test.value)
			} else {
				t.Setenv(name, "")
				if err := os.Unsetenv(name); err != nil {
					t.Fatal(err)
				}
			}

			got, err := Require(name)

			if test.wantErr {
				if err == nil || !strings.Contains(err.Error(), name) {
					t.Errorf("Require(%q) = %q, %v, want an error naming the variable", name, got, err)
				}
			} else if err != nil || got != test.value {
				t.Errorf("Require(%q) = %q, %v, want %q, nil", name, got, err, test.value)
			}
		})
	}
}

func TestWaitForEOF(t *testing.T) {
	if err := WaitForEOF(strings.NewReader("input before EOF")); err != nil {
		t.Errorf("WaitForEOF() returned %v", err)
	}
}

func TestWaitForEOFReturnsReadError(t *testing.T) {
	want := errors.New("read failed")

	err := WaitForEOF(iotest.ErrReader(want))

	if !errors.Is(err, want) {
		t.Errorf("WaitForEOF() returned %v, want %v", err, want)
	}
}

func TestWaitAtGateWithoutAGateReturns(t *testing.T) {
	t.Setenv(GateVariable, "")

	if err := WaitAtGate(); err != nil {
		t.Errorf("WaitAtGate() returned %v", err)
	}
}

func TestWaitAtGateReportsThePIDAndWaitsForTheRelease(t *testing.T) {
	path := gatePath(t)
	listener, err := net.Listen("unix", path)
	if err != nil {
		t.Fatal(err)
	}
	defer listener.Close()
	t.Setenv(GateVariable, path)
	reported := make(chan string, 1)
	go func() {
		conn, err := listener.Accept()
		if err != nil {
			reported <- err.Error()
			return
		}
		defer conn.Close()
		line, _ := bufio.NewReader(conn).ReadString('\n')
		reported <- line
		_, _ = conn.Write([]byte("\n"))
	}()

	err = WaitAtGate()

	if err != nil {
		t.Errorf("WaitAtGate() returned %v", err)
	}
	if got, want := <-reported, strconv.Itoa(os.Getpid())+"\n"; got != want {
		t.Errorf("the gate received %q, want %q", got, want)
	}
}

func TestWaitAtGateFailsWhenClosedWithoutARelease(t *testing.T) {
	path := gatePath(t)
	listener, err := net.Listen("unix", path)
	if err != nil {
		t.Fatal(err)
	}
	defer listener.Close()
	t.Setenv(GateVariable, path)
	go func() {
		if conn, err := listener.Accept(); err == nil {
			_, _ = bufio.NewReader(conn).ReadString('\n')
			_ = conn.Close()
		}
	}()

	if err := WaitAtGate(); err == nil || !strings.Contains(err.Error(), "waiting at the gate") {
		t.Errorf("WaitAtGate() returned %v, want an error waiting at the gate", err)
	}
}

func TestWaitAtGateFailsWithoutAListener(t *testing.T) {
	t.Setenv(GateVariable, gatePath(t))

	if err := WaitAtGate(); err == nil || !strings.Contains(err.Error(), "reaching the gate") {
		t.Errorf("WaitAtGate() returned %v, want an error reaching the gate", err)
	}
}

func gatePath(t *testing.T) string {
	t.Helper()
	dir, err := os.MkdirTemp("", "gate")
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = os.RemoveAll(dir) })
	return filepath.Join(dir, "gate")
}
