/*
 * Copyright The OpenTelemetry Authors
 * SPDX-License-Identifier: Apache-2.0
 */
import io.opentelemetry.conformance.http.jettyhttpclient.JettyHttpClientClientScenario;

public final class JettyHttpClientObiClientScenario {
  private JettyHttpClientObiClientScenario() {}

  public static void main(String[] args) throws Exception {
    JettyHttpClientClientScenario.run();
  }
}
