package com.fintrack.gateway.api;

import com.fintrack.gateway.service.DownstreamCircuitBreaker;
import com.fintrack.gateway.service.FastApiClient;
import java.time.Instant;
import java.util.LinkedHashMap;
import java.util.Map;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RestController;
import reactor.core.publisher.Mono;

@RestController
public class GatewayHealthController {
    private final FastApiClient fastApiClient;
    private final DownstreamCircuitBreaker circuitBreaker;

    public GatewayHealthController(FastApiClient fastApiClient, DownstreamCircuitBreaker circuitBreaker) {
        this.fastApiClient = fastApiClient;
        this.circuitBreaker = circuitBreaker;
    }

    @GetMapping("/")
    Map<String, Object> root() {
        return Map.of(
                "service", "FinTrack Market Gateway",
                "status", "online",
                "authentication", "not_required",
                "personalDataStored", false,
                "health", "/health/ready");
    }

    @GetMapping({"/health", "/health/live"})
    Map<String, Object> live() {
        return Map.of(
                "status", "alive",
                "service", "fintrack-market-gateway",
                "timestamp", Instant.now().toString());
    }

    @GetMapping("/health/ready")
    Mono<ResponseEntity<Map<String, Object>>> ready() {
        return fastApiClient.upstreamReady().map(upstreamReady -> {
            Map<String, Object> body = new LinkedHashMap<>();
            body.put("status", upstreamReady ? "ready" : "not_ready");
            body.put("service", "fintrack-market-gateway");
            body.put("upstream", upstreamReady ? "ready" : "unavailable");
            body.put("circuitBreaker", circuitBreaker.state());
            body.put("authentication", "not_required");
            body.put("personalDataStored", false);
            body.put("timestamp", Instant.now().toString());
            return ResponseEntity.status(upstreamReady ? HttpStatus.OK : HttpStatus.SERVICE_UNAVAILABLE).body(body);
        });
    }
}
