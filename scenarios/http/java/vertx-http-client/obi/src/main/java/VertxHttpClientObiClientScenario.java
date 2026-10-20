/*
 * Copyright The OpenTelemetry Authors
 * SPDX-License-Identifier: Apache-2.0
 */
import io.opentelemetry.conformance.http.vertxhttpclient.VertxHttpClientClientScenario;

public final class VertxHttpClientObiClientScenario {
  private VertxHttpClientObiClientScenario() {}

  public static void main(String[] args) throws Exception {
    VertxHttpClientClientScenario.run();
  }
}
