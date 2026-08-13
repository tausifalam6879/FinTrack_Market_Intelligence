package com.fintrack.gateway.config;

import java.net.URI;
import java.time.Duration;
import java.util.List;
import org.springframework.boot.context.properties.ConfigurationProperties;

@ConfigurationProperties(prefix = "fintrack.gateway")
public record GatewayProperties(
        URI upstreamBaseUrl,
        Duration requestTimeout,
        Duration readinessTimeout,
        int failureThreshold,
        Duration openDuration,
        int maxBodyBytes,
        List<String> allowedOrigins
) {
    public GatewayProperties {
        if (upstreamBaseUrl == null || !List.of("http", "https").contains(upstreamBaseUrl.getScheme())) {
            throw new IllegalArgumentException("A fixed HTTP(S) upstream base URL is required.");
        }
        requestTimeout = positive(requestTimeout, Duration.ofSeconds(75));
        readinessTimeout = positive(readinessTimeout, Duration.ofSeconds(4));
        openDuration = positive(openDuration, Duration.ofSeconds(20));
        failureThreshold = failureThreshold > 0 ? failureThreshold : 3;
        maxBodyBytes = maxBodyBytes > 0 ? maxBodyBytes : 65_536;
        allowedOrigins = allowedOrigins == null ? List.of() : List.copyOf(allowedOrigins);
    }

    private static Duration positive(Duration value, Duration fallback) {
        return value != null && !value.isNegative() && !value.isZero() ? value : fallback;
    }
}
