package com.fintrack.gateway.service;

import com.fintrack.gateway.config.GatewayProperties;
import java.time.Clock;
import java.time.Instant;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.concurrent.atomic.AtomicLong;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Component;

@Component
public class DownstreamCircuitBreaker {
    private final GatewayProperties properties;
    private final Clock clock;
    private final AtomicInteger consecutiveFailures = new AtomicInteger();
    private final AtomicLong openUntilEpochMillis = new AtomicLong();

    @Autowired
    public DownstreamCircuitBreaker(GatewayProperties properties) {
        this(properties, Clock.systemUTC());
    }

    DownstreamCircuitBreaker(GatewayProperties properties, Clock clock) {
        this.properties = properties;
        this.clock = clock;
    }

    public boolean allowRequest() {
        return clock.millis() >= openUntilEpochMillis.get();
    }

    public void recordSuccess() {
        consecutiveFailures.set(0);
        openUntilEpochMillis.set(0);
    }

    public void recordFailure() {
        int failures = consecutiveFailures.incrementAndGet();
        if (failures >= properties.failureThreshold()) {
            openUntilEpochMillis.set(clock.millis() + properties.openDuration().toMillis());
        }
    }

    public State state() {
        long openUntil = openUntilEpochMillis.get();
        return new State(
                allowRequest() ? "closed" : "open",
                consecutiveFailures.get(),
                openUntil == 0 ? null : Instant.ofEpochMilli(openUntil));
    }

    public record State(String status, int consecutiveFailures, Instant openUntil) { }
}
