/*
 * Copyright The OpenTelemetry Authors
 * SPDX-License-Identifier: Apache-2.0
 */
import io.opentelemetry.conformance.http.javahttpclient.JavaHttpClientClientScenario;

public final class JavaHttpClientObiClientScenario {
  private JavaHttpClientObiClientScenario() {}

  public static void main(String[] args) throws Exception {
    JavaHttpClientClientScenario.run();
  }
}
