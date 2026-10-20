/*
 * Copyright The OpenTelemetry Authors
 * SPDX-License-Identifier: Apache-2.0
 */
import io.opentelemetry.conformance.http.tomcat.TomcatServerScenario;

public final class TomcatObiServerScenario {
  private TomcatObiServerScenario() {}

  public static void main(String[] args) throws Exception {
    TomcatServerScenario.run();
  }
}
