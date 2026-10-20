/*
 * Copyright The OpenTelemetry Authors
 * SPDX-License-Identifier: Apache-2.0
 */
import io.opentelemetry.conformance.http.ratpack.RatpackServerScenario;

public final class RatpackObiServerScenario {
  private RatpackObiServerScenario() {}

  public static void main(String[] args) throws Exception {
    RatpackServerScenario.run();
  }
}
