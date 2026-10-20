/*
 * Copyright The OpenTelemetry Authors
 * SPDX-License-Identifier: Apache-2.0
 */
import io.opentelemetry.conformance.http.javahttpserver.JavaHttpServerServerScenario;

public final class JavaHttpServerObiServerScenario {
  private JavaHttpServerObiServerScenario() {}

  public static void main(String[] args) throws Exception {
    JavaHttpServerServerScenario.run();
  }
}
