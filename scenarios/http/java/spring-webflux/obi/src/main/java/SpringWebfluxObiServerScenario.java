/*
 * Copyright The OpenTelemetry Authors
 * SPDX-License-Identifier: Apache-2.0
 */
import io.opentelemetry.conformance.http.springwebflux.SpringWebfluxServerScenario;

public final class SpringWebfluxObiServerScenario {
  private SpringWebfluxObiServerScenario() {}

  public static void main(String[] args) throws Exception {
    SpringWebfluxServerScenario.run();
  }
}
