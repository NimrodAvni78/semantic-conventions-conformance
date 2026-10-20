/*
 * Copyright The OpenTelemetry Authors
 * SPDX-License-Identifier: Apache-2.0
 */
import io.opentelemetry.conformance.http.ktor.KtorClientScenario

object KtorObiClientScenario {
    @JvmStatic
    fun main(args: Array<String>) {
        KtorClientScenario.run {}
    }
}
