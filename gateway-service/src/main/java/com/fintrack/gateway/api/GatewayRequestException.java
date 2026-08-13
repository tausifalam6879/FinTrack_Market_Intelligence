package com.fintrack.gateway.api;

import org.springframework.http.HttpStatus;

public class GatewayRequestException extends RuntimeException {
    private final HttpStatus status;
    private final String code;

    public GatewayRequestException(HttpStatus status, String code, String message) {
        super(message);
        this.status = status;
        this.code = code;
    }

    public HttpStatus status() {
        return status;
    }

    public String code() {
        return code;
    }
}
