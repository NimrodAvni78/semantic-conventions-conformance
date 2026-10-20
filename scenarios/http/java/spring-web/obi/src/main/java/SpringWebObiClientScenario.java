/*
 * Copyright The OpenTelemetry Authors
 * SPDX-License-Identifier: Apache-2.0
 */
import io.opentelemetry.conformance.http.springweb.SpringWebClientScenario;

public final class SpringWebObiClientScenario {
  private SpringWebObiClientScenario() {}

  public static void main(String[] args) throws Exception {
    SpringWebClientScenario.run(restTemplate -> {});
  }
}
