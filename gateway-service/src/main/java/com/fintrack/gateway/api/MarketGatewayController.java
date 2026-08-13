package com.fintrack.gateway.api;

import com.fintrack.gateway.config.GatewayProperties;
import com.fintrack.gateway.service.FastApiClient;
import com.fintrack.gateway.validation.GatewayRequestValidator;
import java.util.UUID;
import org.springframework.core.io.buffer.DataBufferUtils;
import org.springframework.http.CacheControl;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpMethod;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestMethod;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.server.ServerWebExchange;
import reactor.core.publisher.Mono;

@RestController
public class MarketGatewayController {
    public static final String REQUEST_ID_ATTRIBUTE = "fintrackRequestId";
    private final FastApiClient fastApiClient;
    private final GatewayRequestValidator validator;
    private final GatewayProperties properties;

    public MarketGatewayController(
            FastApiClient fastApiClient,
            GatewayRequestValidator validator,
            GatewayProperties properties) {
        this.fastApiClient = fastApiClient;
        this.validator = validator;
        this.properties = properties;
    }

    @RequestMapping(value = "/market/**", method = {RequestMethod.GET, RequestMethod.POST})
    public Mono<ResponseEntity<byte[]>> proxy(ServerWebExchange exchange) {
        String path = exchange.getRequest().getPath().pathWithinApplication().value();
        HttpMethod method = exchange.getRequest().getMethod();
        String suppliedRequestId = exchange.getRequest().getHeaders().getFirst("X-Request-Id");
        String requestId = validator.validRequestId(suppliedRequestId)
                ? suppliedRequestId
                : UUID.randomUUID().toString();
        exchange.getAttributes().put(REQUEST_ID_ATTRIBUTE, requestId);

        return readBody(exchange)
                .doOnNext(body -> validator.validate(method, path, exchange.getRequest().getQueryParams(), body))
                .flatMap(body -> fastApiClient.forward(
                        method, path, exchange.getRequest().getQueryParams(), body, requestId))
                .map(upstream -> ResponseEntity.status(upstream.status())
                        .contentType(upstream.contentType())
                        .cacheControl(CacheControl.noStore())
                        .header("X-Request-Id", requestId)
                        .header("X-FinTrack-Gateway", "spring-boot")
                        .body(upstream.body()));
    }

    private Mono<byte[]> readBody(ServerWebExchange exchange) {
        String contentLength = exchange.getRequest().getHeaders().getFirst(HttpHeaders.CONTENT_LENGTH);
        if (contentLength != null) {
            try {
                if (Long.parseLong(contentLength) > properties.maxBodyBytes()) {
                    return Mono.error(bodyTooLarge());
                }
            } catch (NumberFormatException exception) {
                return Mono.error(new GatewayRequestException(
                        org.springframework.http.HttpStatus.BAD_REQUEST,
                        "invalid_content_length",
                        "Content-Length must be valid."));
            }
        }

        return DataBufferUtils.join(exchange.getRequest().getBody(), properties.maxBodyBytes())
                .map(buffer -> {
                    byte[] bytes = new byte[buffer.readableByteCount()];
                    buffer.read(bytes);
                    DataBufferUtils.release(buffer);
                    return bytes;
                })
                .defaultIfEmpty(new byte[0])
                .onErrorMap(org.springframework.core.io.buffer.DataBufferLimitException.class, ignored -> bodyTooLarge());
    }

    private GatewayRequestException bodyTooLarge() {
        return new GatewayRequestException(
                org.springframework.http.HttpStatus.CONTENT_TOO_LARGE,
                "body_too_large",
                "The public gateway accepts request bodies up to 64 KB.");
    }
}
