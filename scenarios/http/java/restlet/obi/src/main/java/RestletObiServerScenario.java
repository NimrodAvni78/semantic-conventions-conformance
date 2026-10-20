/*
 * Copyright The OpenTelemetry Authors
 * SPDX-License-Identifier: Apache-2.0
 */
import io.opentelemetry.conformance.http.restlet.RestletServerScenario;

public final class RestletObiServerScenario {
  private RestletObiServerScenario() {}

  public static void main(String[] args) throws Exception {
    RestletServerScenario.run();
  }
}
