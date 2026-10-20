/*
 * Copyright The OpenTelemetry Authors
 * SPDX-License-Identifier: Apache-2.0
 */
import io.opentelemetry.conformance.http.servlet.ServletServerScenario;

public final class ServletObiServerScenario {
  private ServletObiServerScenario() {}

  public static void main(String[] args) throws Exception {
    ServletServerScenario.run();
  }
}
