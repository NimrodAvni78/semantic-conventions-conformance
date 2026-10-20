/*
 * Copyright The OpenTelemetry Authors
 * SPDX-License-Identifier: Apache-2.0
 */
import io.opentelemetry.conformance.http.netty.NettyClientScenario;

public final class NettyObiClientScenario {
  private NettyObiClientScenario() {}

  public static void main(String[] args) throws Exception {
    NettyClientScenario.run();
  }
}
