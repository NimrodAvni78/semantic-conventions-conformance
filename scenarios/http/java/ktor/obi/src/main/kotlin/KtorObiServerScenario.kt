/*
 * Copyright The OpenTelemetry Authors
 * SPDX-License-Identifier: Apache-2.0
 */
import io.opentelemetry.conformance.http.ktor.KtorServerScenario

object KtorObiServerScenario {
    @JvmStatic
    fun main(args: Array<String>) {
        KtorServerScenario.run {}
    }
}
