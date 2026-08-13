package com.fintrack.gateway.validation;

import static org.junit.jupiter.api.Assertions.assertDoesNotThrow;
import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;

import com.fintrack.gateway.api.GatewayRequestException;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.http.HttpMethod;
import org.springframework.util.LinkedMultiValueMap;
import org.springframework.util.MultiValueMap;
import tools.jackson.databind.json.JsonMapper;

class GatewayRequestValidatorTest {
    private GatewayRequestValidator validator;

    @BeforeEach
    void setUp() {
        validator = new GatewayRequestValidator(JsonMapper.builder().build());
    }

    @Test
    void acceptsAnyWellFormedDynamicSymbol() {
        MultiValueMap<String, String> query = new LinkedMultiValueMap<>();
        query.add("symbol", "510370.SS");
        query.add("refresh", "false");
        assertDoesNotThrow(() -> validator.validate(HttpMethod.GET, "/market/analysis", query, new byte[0]));
    }

    @Test
    void blocksRoutesOutsideThePublicAllowlist() {
        GatewayRequestException exception = assertThrows(GatewayRequestException.class,
                () -> validator.validate(HttpMethod.GET, "/market/admin", new LinkedMultiValueMap<>(), new byte[0]));
        assertEquals("route_not_found", exception.code());
    }

    @Test
    void rejectsInvalidSymbolsBeforeTheyReachPython() {
        MultiValueMap<String, String> query = new LinkedMultiValueMap<>();
        query.add("symbol", "https://attacker.example/file");
        GatewayRequestException exception = assertThrows(GatewayRequestException.class,
                () -> validator.validate(HttpMethod.GET, "/market/analysis", query, new byte[0]));
        assertEquals("invalid_symbol", exception.code());
    }

    @Test
    void rejectsMutationFieldsOnPublicDocumentPreparation() {
        byte[] body = "{\"symbol\":\"INFY.NS\",\"url\":\"https://example.com/report.pdf\"}".getBytes();
        GatewayRequestException exception = assertThrows(GatewayRequestException.class,
                () -> validator.validate(HttpMethod.POST, "/market/documents/prepare", new LinkedMultiValueMap<>(), body));
        assertEquals("unexpected_field", exception.code());
    }

    @Test
    void acceptsGroundedAgentPayload() {
        byte[] body = "{\"symbol\":\"AAPL\",\"message\":\"Explain the current evidence\",\"recentMessages\":[]}".getBytes();
        assertDoesNotThrow(() -> validator.validate(
                HttpMethod.POST, "/market/agent", new LinkedMultiValueMap<>(), body));
    }
}
