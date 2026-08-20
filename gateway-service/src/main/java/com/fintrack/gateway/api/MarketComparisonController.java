package com.fintrack.gateway.api;

import com.fintrack.gateway.service.ComparisonService;
import com.fintrack.gateway.validation.GatewayRequestValidator;
import java.util.ArrayList;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.UUID;
import java.util.regex.Pattern;
import org.springframework.http.CacheControl;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.server.ServerWebExchange;
import reactor.core.publisher.Mono;

@RestController
public class MarketComparisonController {
    private static final Pattern SYMBOL = Pattern.compile("^[A-Za-z0-9.^=_:-]{1,40}$");
    private final ComparisonService comparisonService;
    private final GatewayRequestValidator validator;

    public MarketComparisonController(ComparisonService comparisonService, GatewayRequestValidator validator) {
        this.comparisonService = comparisonService;
        this.validator = validator;
    }

    @PostMapping("/market/compare")
    public Mono<ResponseEntity<Map<String, Object>>> compare(
            @RequestBody ComparisonRequest request, ServerWebExchange exchange) {
        List<String> symbols = validateSymbols(request == null ? null : request.symbols());
        String suppliedRequestId = exchange.getRequest().getHeaders().getFirst("X-Request-Id");
        String requestId = validator.validRequestId(suppliedRequestId) ? suppliedRequestId : UUID.randomUUID().toString();
        exchange.getAttributes().put(MarketGatewayController.REQUEST_ID_ATTRIBUTE, requestId);
        boolean refresh = request != null && Boolean.TRUE.equals(request.refresh());
        return comparisonService.compare(symbols, refresh, requestId)
                .map(body -> ResponseEntity.ok()
                        .cacheControl(CacheControl.noStore())
                        .header("X-Request-Id", requestId)
                        .header("X-FinTrack-Gateway", "spring-boot-batch")
                        .body(body));
    }

    private List<String> validateSymbols(List<String> rawSymbols) {
        if (rawSymbols == null || rawSymbols.size() < 2 || rawSymbols.size() > 4) {
            throw new GatewayRequestException(HttpStatus.BAD_REQUEST, "invalid_comparison_size", "Select between two and four symbols.");
        }
        List<String> symbols = new ArrayList<>();
        for (String raw : rawSymbols) {
            String symbol = raw == null ? "" : raw.trim().toUpperCase(Locale.ROOT);
            if (!SYMBOL.matcher(symbol).matches()) {
                throw new GatewayRequestException(HttpStatus.BAD_REQUEST, "invalid_symbol", "The market symbol format is invalid.");
            }
            if (!symbols.contains(symbol)) symbols.add(symbol);
        }
        if (symbols.size() < 2) {
            throw new GatewayRequestException(HttpStatus.BAD_REQUEST, "duplicate_symbols", "Select at least two unique symbols.");
        }
        return List.copyOf(symbols);
    }

    public record ComparisonRequest(List<String> symbols, Boolean refresh) { }
}
