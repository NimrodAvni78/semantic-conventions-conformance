/*
 * Copyright The OpenTelemetry Authors
 * SPDX-License-Identifier: Apache-2.0
 */
import io.opentelemetry.conformance.http.apachehttpasyncclient.ApacheHttpAsyncClientClientScenario;

public final class ApacheHttpAsyncClientObiClientScenario {
  private ApacheHttpAsyncClientObiClientScenario() {}

  public static void main(String[] args) throws Exception {
    ApacheHttpAsyncClientClientScenario.run();
  }
}
