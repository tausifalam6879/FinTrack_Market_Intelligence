package com.fintrack.gateway.service;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

import com.fintrack.gateway.config.GatewayProperties;
import java.net.URI;
import java.time.Clock;
import java.time.Duration;
import java.time.Instant;
import java.time.ZoneOffset;
import java.util.List;
import org.junit.jupiter.api.Test;

class DownstreamCircuitBreakerTest {
    @Test
    void opensAfterConfiguredConsecutiveFailuresAndResetsOnSuccess() {
        GatewayProperties properties = new GatewayProperties(
                URI.create("http://127.0.0.1:8002"), Duration.ofSeconds(5), Duration.ofSeconds(2),
                3, Duration.ofSeconds(20), 65_536, List.of());
        Clock clock = Clock.fixed(Instant.parse("2026-08-13T12:00:00Z"), ZoneOffset.UTC);
        DownstreamCircuitBreaker breaker = new DownstreamCircuitBreaker(properties, clock);

        breaker.recordFailure();
        breaker.recordFailure();
        assertTrue(breaker.allowRequest());
        breaker.recordFailure();
        assertFalse(breaker.allowRequest());
        assertEquals("open", breaker.state().status());

        breaker.recordSuccess();
        assertTrue(breaker.allowRequest());
        assertEquals("closed", breaker.state().status());
    }
}
