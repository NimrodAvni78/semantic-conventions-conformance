/*
 * Copyright The OpenTelemetry Authors
 * SPDX-License-Identifier: Apache-2.0
 */
import io.opentelemetry.conformance.http.joddhttp.JoddHttpClientScenario;

public final class JoddHttpObiClientScenario {
  private JoddHttpObiClientScenario() {}

  public static void main(String[] args) throws Exception {
    JoddHttpClientScenario.run();
  }
}
