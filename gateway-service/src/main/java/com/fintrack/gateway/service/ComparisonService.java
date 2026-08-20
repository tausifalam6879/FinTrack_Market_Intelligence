package com.fintrack.gateway.service;

import com.fintrack.gateway.api.UpstreamUnavailableException;
import io.micrometer.core.instrument.MeterRegistry;
import java.time.Duration;
import java.time.Instant;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;
import org.springframework.http.HttpStatusCode;
import org.springframework.stereotype.Service;
import reactor.core.publisher.Flux;
import reactor.core.publisher.Mono;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.ObjectMapper;

@Service
public class ComparisonService {
    private static final Duration CACHE_TTL = Duration.ofMinutes(5);
    private static final int MAX_CONCURRENCY = 4;

    private final FastApiClient fastApiClient;
    private final ObjectMapper objectMapper;
    private final MeterRegistry meterRegistry;
    private final Map<String, CachedComparison> cache = new ConcurrentHashMap<>();

    public ComparisonService(FastApiClient fastApiClient, ObjectMapper objectMapper, MeterRegistry meterRegistry) {
        this.fastApiClient = fastApiClient;
        this.objectMapper = objectMapper;
        this.meterRegistry = meterRegistry;
    }

    public Mono<Map<String, Object>> compare(List<String> symbols, boolean refresh, String requestId) {
        String key = String.join("|", symbols);
        CachedComparison cached = cache.get(key);
        if (!refresh && cached != null && Duration.between(cached.createdAt(), Instant.now()).compareTo(CACHE_TTL) < 0) {
            meterRegistry.counter("fintrack.gateway.comparison.cache", "result", "hit").increment();
            Map<String, Object> response = new LinkedHashMap<>(cached.response());
            response.put("cache", "spring-memory-hit");
            return Mono.just(response);
        }

        meterRegistry.counter("fintrack.gateway.comparison.cache", "result", "miss").increment();
        long started = System.nanoTime();
        return Flux.fromIterable(symbols)
                .flatMapSequential(symbol -> fastApiClient.analysis(symbol, refresh, requestId + ":" + symbol)
                        .map(response -> decode(symbol, response))
                        .onErrorResume(error -> Mono.just(ComparisonItem.error(symbol))), MAX_CONCURRENCY, 1)
                .collectList()
                .flatMap(results -> {
                    List<JsonNode> items = new ArrayList<>();
                    List<Map<String, String>> errors = new ArrayList<>();
                    results.forEach(result -> {
                        if (result.data() != null) items.add(result.data());
                        else errors.add(Map.of("symbol", result.symbol(), "message", "Verified analysis is temporarily unavailable."));
                    });
                    if (items.isEmpty()) {
                        return Mono.error(new UpstreamUnavailableException(
                                "comparison_unavailable", "Comparison data is temporarily unavailable."));
                    }
                    Map<String, Object> response = new LinkedHashMap<>();
                    response.put("symbols", symbols);
                    response.put("items", items);
                    response.put("errors", errors);
                    response.put("partial", !errors.isEmpty());
                    response.put("execution", "parallel-spring-webclient");
                    response.put("cache", "spring-memory-miss");
                    response.put("durationMs", Math.round((System.nanoTime() - started) / 100_000.0) / 10.0);
                    response.put("generatedAt", Instant.now().toString());
                    cache.put(key, new CachedComparison(Instant.now(), Map.copyOf(response)));
                    return Mono.just(response);
                });
    }

    private ComparisonItem decode(String symbol, FastApiClient.UpstreamResponse response) {
        HttpStatusCode status = response.status();
        if (!status.is2xxSuccessful()) return ComparisonItem.error(symbol);
        try {
            return new ComparisonItem(symbol, objectMapper.readTree(response.body()));
        } catch (RuntimeException exception) {
            return ComparisonItem.error(symbol);
        }
    }

    private record ComparisonItem(String symbol, JsonNode data) {
        static ComparisonItem error(String symbol) { return new ComparisonItem(symbol, null); }
    }

    private record CachedComparison(Instant createdAt, Map<String, Object> response) { }
}
