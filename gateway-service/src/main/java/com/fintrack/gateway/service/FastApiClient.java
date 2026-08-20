package com.fintrack.gateway.service;

import com.fintrack.gateway.api.UpstreamUnavailableException;
import com.fintrack.gateway.config.GatewayProperties;
import io.micrometer.core.instrument.MeterRegistry;
import io.micrometer.core.instrument.Timer;
import java.time.Duration;
import java.util.concurrent.TimeoutException;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpMethod;
import org.springframework.http.HttpStatusCode;
import org.springframework.http.MediaType;
import org.springframework.stereotype.Service;
import org.springframework.util.MultiValueMap;
import org.springframework.util.LinkedMultiValueMap;
import org.springframework.web.reactive.function.BodyInserters;
import org.springframework.web.reactive.function.client.WebClient;
import org.springframework.web.reactive.function.client.WebClientRequestException;
import reactor.core.publisher.Mono;
import reactor.util.retry.Retry;

@Service
public class FastApiClient {
    private final WebClient webClient;
    private final GatewayProperties properties;
    private final DownstreamCircuitBreaker circuitBreaker;
    private final MeterRegistry meterRegistry;

    public FastApiClient(
            WebClient upstreamWebClient,
            GatewayProperties properties,
            DownstreamCircuitBreaker circuitBreaker,
            MeterRegistry meterRegistry) {
        this.webClient = upstreamWebClient;
        this.properties = properties;
        this.circuitBreaker = circuitBreaker;
        this.meterRegistry = meterRegistry;
    }

    public Mono<UpstreamResponse> forward(
            HttpMethod method,
            String path,
            MultiValueMap<String, String> query,
            byte[] body,
            String requestId) {
        if (!circuitBreaker.allowRequest()) {
            meterRegistry.counter("fintrack.gateway.rejected", "reason", "circuit_open").increment();
            return Mono.error(new UpstreamUnavailableException(
                    "upstream_circuit_open", "Market intelligence is recovering. Please retry shortly."));
        }

        Timer.Sample sample = Timer.start(meterRegistry);
        WebClient.RequestBodySpec request = webClient
                .method(method)
                .uri(builder -> {
                    builder.path(path);
                    query.forEach((key, values) -> values.forEach(value -> builder.queryParam(key, value)));
                    return builder.build();
                })
                .header("X-Request-Id", requestId)
                .header(HttpHeaders.ACCEPT, MediaType.APPLICATION_JSON_VALUE);

        if (HttpMethod.POST.equals(method)) {
            request.header(HttpHeaders.CONTENT_TYPE, MediaType.APPLICATION_JSON_VALUE)
                    .body(BodyInserters.fromValue(body));
        }

        return request.exchangeToMono(response -> response.bodyToMono(byte[].class)
                        .defaultIfEmpty(new byte[0])
                        .flatMap(responseBody -> {
                            if (response.statusCode().is5xxServerError()) {
                                return Mono.error(new UpstreamUnavailableException(
                                        "upstream_failure", "The market intelligence service is temporarily unavailable."));
                            }
                            return Mono.just(new UpstreamResponse(
                                    response.statusCode(),
                                    response.headers().contentType().orElse(MediaType.APPLICATION_JSON),
                                    responseBody));
                        }))
                .timeout(properties.requestTimeout())
                .retryWhen(Retry.fixedDelay(1, Duration.ofMillis(350))
                        .filter(error -> HttpMethod.GET.equals(method) && (
                                error instanceof TimeoutException
                                        || error instanceof WebClientRequestException
                                        || error instanceof UpstreamUnavailableException))
                        .doBeforeRetry(ignored -> meterRegistry.counter(
                                "fintrack.gateway.retries", "route", path).increment()))
                .doOnNext(ignored -> circuitBreaker.recordSuccess())
                .doOnError(ignored -> circuitBreaker.recordFailure())
                .onErrorMap(TimeoutException.class, ignored -> new UpstreamUnavailableException(
                        "upstream_timeout", "The market intelligence request timed out."))
                .onErrorMap(WebClientRequestException.class, ignored -> new UpstreamUnavailableException(
                        "upstream_unreachable", "The market intelligence service is starting or unavailable."))
                .doFinally(signal -> sample.stop(Timer.builder("fintrack.gateway.requests")
                        .description("Validated public gateway requests")
                        .tag("method", method.name())
                        .tag("route", path)
                        .tag("outcome", signal.name().toLowerCase())
                        .register(meterRegistry)));
    }

    public Mono<Boolean> upstreamReady() {
        Duration timeout = properties.readinessTimeout();
        return webClient.get()
                .uri("/health/ready")
                .exchangeToMono(response -> Mono.just(response.statusCode().is2xxSuccessful()))
                .timeout(timeout)
                .onErrorReturn(false);
    }

    public Mono<UpstreamResponse> analysis(String symbol, boolean refresh, String requestId) {
        MultiValueMap<String, String> query = new LinkedMultiValueMap<>();
        query.add("symbol", symbol);
        query.add("refresh", Boolean.toString(refresh));
        return forward(HttpMethod.GET, "/market/analysis", query, new byte[0], requestId);
    }

    public record UpstreamResponse(HttpStatusCode status, MediaType contentType, byte[] body) { }
}
