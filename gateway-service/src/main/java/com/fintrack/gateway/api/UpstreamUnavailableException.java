package com.fintrack.gateway.api;

public class UpstreamUnavailableException extends RuntimeException {
    private final String code;

    public UpstreamUnavailableException(String code, String message) {
        super(message);
        this.code = code;
    }

    public String code() {
        return code;
    }
}
