package com.fintrack.gateway.api;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.mockito.Mockito.mock;

import com.fintrack.gateway.service.ComparisonService;
import com.fintrack.gateway.validation.GatewayRequestValidator;
import java.util.List;
import org.junit.jupiter.api.Test;
import org.springframework.mock.http.server.reactive.MockServerHttpRequest;
import org.springframework.mock.web.server.MockServerWebExchange;
import tools.jackson.databind.json.JsonMapper;

class MarketComparisonControllerTest {
    @Test
    void rejectsDuplicateOrUnsafeSymbolsBeforeCallingUpstream() {
        MarketComparisonController controller = new MarketComparisonController(
                mock(ComparisonService.class), new GatewayRequestValidator(JsonMapper.builder().build()));
        MockServerWebExchange exchange = MockServerWebExchange.from(MockServerHttpRequest.post("/market/compare"));

        GatewayRequestException duplicate = assertThrows(GatewayRequestException.class, () -> controller.compare(
                new MarketComparisonController.ComparisonRequest(List.of("AAPL", "aapl"), false), exchange));
        assertEquals("duplicate_symbols", duplicate.code());

        GatewayRequestException unsafe = assertThrows(GatewayRequestException.class, () -> controller.compare(
                new MarketComparisonController.ComparisonRequest(List.of("AAPL", "https://bad.example"), false), exchange));
        assertEquals("invalid_symbol", unsafe.code());
    }
}
