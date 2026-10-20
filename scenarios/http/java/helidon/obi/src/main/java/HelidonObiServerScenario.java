/*
 * Copyright The OpenTelemetry Authors
 * SPDX-License-Identifier: Apache-2.0
 */
import io.opentelemetry.conformance.http.helidon.HelidonServerScenario;

public final class HelidonObiServerScenario {
  private HelidonObiServerScenario() {}

  public static void main(String[] args) throws Exception {
    HelidonServerScenario.run();
  }
}
