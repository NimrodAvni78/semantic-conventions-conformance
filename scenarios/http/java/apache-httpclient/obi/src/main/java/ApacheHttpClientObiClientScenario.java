/*
 * Copyright The OpenTelemetry Authors
 * SPDX-License-Identifier: Apache-2.0
 */
import io.opentelemetry.conformance.http.apachehttpclient.ApacheHttpClientClientScenario;

public final class ApacheHttpClientObiClientScenario {
  private ApacheHttpClientObiClientScenario() {}

  public static void main(String[] args) throws Exception {
    ApacheHttpClientClientScenario.run();
  }
}
