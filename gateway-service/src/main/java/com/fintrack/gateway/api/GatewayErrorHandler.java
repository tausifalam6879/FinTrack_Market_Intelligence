package com.fintrack.gateway.api;

import java.time.Instant;
import java.util.Map;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.RestControllerAdvice;
import org.springframework.web.server.ServerWebExchange;

@RestControllerAdvice
public class GatewayErrorHandler {
    @ExceptionHandler(GatewayRequestException.class)
    ResponseEntity<Map<String, Object>> requestError(GatewayRequestException exception, ServerWebExchange exchange) {
        return error(exception.status(), exception.code(), exception.getMessage(), exchange);
    }

    @ExceptionHandler(UpstreamUnavailableException.class)
    ResponseEntity<Map<String, Object>> upstreamError(UpstreamUnavailableException exception, ServerWebExchange exchange) {
        return error(HttpStatus.SERVICE_UNAVAILABLE, exception.code(), exception.getMessage(), exchange);
    }

    @ExceptionHandler(Exception.class)
    ResponseEntity<Map<String, Object>> unexpectedError(Exception exception, ServerWebExchange exchange) {
        return error(HttpStatus.INTERNAL_SERVER_ERROR, "gateway_error", "The public gateway could not complete the request.", exchange);
    }

    private ResponseEntity<Map<String, Object>> error(
            HttpStatus status,
            String code,
            String message,
            ServerWebExchange exchange) {
        String requestId = String.valueOf(exchange.getAttributeOrDefault(
                MarketGatewayController.REQUEST_ID_ATTRIBUTE, "unavailable"));
        return ResponseEntity.status(status)
                .header("X-Request-Id", requestId)
                .header("X-FinTrack-Gateway", "spring-boot")
                .body(Map.of(
                        "status", status.value(),
                        "code", code,
                        "message", message,
                        "requestId", requestId,
                        "timestamp", Instant.now().toString()));
    }
}
