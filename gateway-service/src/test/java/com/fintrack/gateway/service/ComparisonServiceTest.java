package com.fintrack.gateway.service;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.mockito.ArgumentMatchers.anyBoolean;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.times;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import io.micrometer.core.instrument.simple.SimpleMeterRegistry;
import java.nio.charset.StandardCharsets;
import java.util.List;
import java.util.Map;
import org.junit.jupiter.api.Test;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import reactor.core.publisher.Mono;
import tools.jackson.databind.json.JsonMapper;

class ComparisonServiceTest {
    @Test
    void fetchesInParallelShapeAndReusesShortLivedGatewayCache() {
        FastApiClient client = mock(FastApiClient.class);
        when(client.analysis(anyString(), anyBoolean(), anyString())).thenAnswer(invocation -> {
            String symbol = invocation.getArgument(0);
            byte[] body = ("{\"symbol\":\"" + symbol + "\",\"outlook\":\"NEUTRAL\"}")
                    .getBytes(StandardCharsets.UTF_8);
            return Mono.just(new FastApiClient.UpstreamResponse(HttpStatus.OK, MediaType.APPLICATION_JSON, body));
        });
        ComparisonService service = new ComparisonService(client, JsonMapper.builder().build(), new SimpleMeterRegistry());

        Map<String, Object> first = service.compare(List.of("AAPL", "MSFT"), false, "test-request").block();
        Map<String, Object> second = service.compare(List.of("AAPL", "MSFT"), false, "test-request-2").block();

        assertNotNull(first);
        assertEquals("parallel-spring-webclient", first.get("execution"));
        assertEquals(2, ((List<?>) first.get("items")).size());
        assertEquals("spring-memory-hit", second.get("cache"));
        verify(client, times(2)).analysis(anyString(), anyBoolean(), anyString());
    }
}
