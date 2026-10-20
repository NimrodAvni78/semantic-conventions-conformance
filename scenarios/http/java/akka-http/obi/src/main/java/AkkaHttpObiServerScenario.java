/*
 * Copyright The OpenTelemetry Authors
 * SPDX-License-Identifier: Apache-2.0
 */
import io.opentelemetry.conformance.http.akkahttp.AkkaHttpServerScenario;

public final class AkkaHttpObiServerScenario {
  private AkkaHttpObiServerScenario() {}

  public static void main(String[] args) throws Exception {
    AkkaHttpServerScenario.run();
  }
}
