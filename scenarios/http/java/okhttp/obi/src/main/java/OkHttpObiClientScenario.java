/*
 * Copyright The OpenTelemetry Authors
 * SPDX-License-Identifier: Apache-2.0
 */
import io.opentelemetry.conformance.http.okhttp.OkHttpClientScenario;

public final class OkHttpObiClientScenario {
  private OkHttpObiClientScenario() {}

  public static void main(String[] args) throws Exception {
    OkHttpClientScenario.run();
  }
}
