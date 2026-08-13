package com.fintrack.gateway.validation;

import com.fintrack.gateway.api.GatewayRequestException;
import java.nio.charset.StandardCharsets;
import java.util.Map;
import java.util.Set;
import java.util.regex.Pattern;
import org.springframework.http.HttpMethod;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Component;
import org.springframework.util.MultiValueMap;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.ObjectMapper;

@Component
public class GatewayRequestValidator {
    private static final Pattern SYMBOL = Pattern.compile("^[A-Za-z0-9.^=_:-]{1,40}$");
    private static final Pattern REQUEST_ID = Pattern.compile("^[A-Za-z0-9._:-]{1,80}$");
    private static final Set<String> SYMBOL_REQUIRED = Set.of(
            "/market/analysis", "/market/predictions", "/market/company", "/market/peer-comparison",
            "/market/model-status", "/market/model-drift", "/market/data-operations",
            "/market/experiments", "/market/documents", "/market/documents/discover");
    private static final Map<String, Set<String>> GET_ROUTES = Map.ofEntries(
            Map.entry("/market/overview", Set.of("refresh")),
            Map.entry("/market/currencies", Set.of("refresh")),
            Map.entry("/market/analysis", Set.of("symbol", "refresh")),
            Map.entry("/market/predictions", Set.of("symbol", "limit")),
            Map.entry("/market/news", Set.of("symbol", "limit")),
            Map.entry("/market/factors", Set.of("refresh")),
            Map.entry("/market/breadth", Set.of("refresh")),
            Map.entry("/market/company", Set.of("symbol", "refresh")),
            Map.entry("/market/peer-comparison", Set.of("symbol", "refresh")),
            Map.entry("/market/news-feed", Set.of("refresh", "limit")),
            Map.entry("/market/companies", Set.of("q", "limit")),
            Map.entry("/market/model-status", Set.of("symbol")),
            Map.entry("/market/model-drift", Set.of("symbol")),
            Map.entry("/market/data-operations", Set.of("symbol")),
            Map.entry("/market/database-status", Set.of()),
            Map.entry("/market/experiments", Set.of("symbol", "limit")),
            Map.entry("/market/documents", Set.of("symbol")),
            Map.entry("/market/documents/discover", Set.of("symbol")));
    private static final Map<String, Set<String>> POST_ROUTES = Map.of(
            "/market/agent", Set.of("message", "symbol", "recentMessages"),
            "/market/documents/ask", Set.of("symbol", "question", "limit"),
            "/market/documents/prepare", Set.of("symbol"));

    private final ObjectMapper objectMapper;

    public GatewayRequestValidator(ObjectMapper objectMapper) {
        this.objectMapper = objectMapper;
    }

    public void validate(HttpMethod method, String path, MultiValueMap<String, String> query, byte[] body) {
        if (HttpMethod.GET.equals(method)) {
            validateGet(path, query);
            if (body.length > 0) badRequest("unexpected_body", "GET requests cannot contain a body.");
            return;
        }
        if (HttpMethod.POST.equals(method)) {
            validatePost(path, query, body);
            return;
        }
        throw new GatewayRequestException(HttpStatus.METHOD_NOT_ALLOWED, "method_not_allowed", "Only GET and POST are supported.");
    }

    public boolean validRequestId(String value) {
        return value != null && REQUEST_ID.matcher(value).matches();
    }

    private void validateGet(String path, MultiValueMap<String, String> query) {
        Set<String> allowed = GET_ROUTES.get(path);
        if (allowed == null) notFound();
        rejectUnknownQueryParameters(query, allowed);
        validateCommonQuery(query);
        if (SYMBOL_REQUIRED.contains(path) && blank(query.getFirst("symbol"))) {
            badRequest("symbol_required", "A valid market symbol is required.");
        }
        String search = query.getFirst("q");
        if ("/market/companies".equals(path) && (blank(search) || search.trim().length() < 2 || search.length() > 80)) {
            badRequest("invalid_search", "Company search must contain between 2 and 80 characters.");
        }
    }

    private void validatePost(String path, MultiValueMap<String, String> query, byte[] body) {
        Set<String> allowedFields = POST_ROUTES.get(path);
        if (allowedFields == null) notFound();
        if (!query.isEmpty()) badRequest("unexpected_query", "This POST route does not accept query parameters.");
        if (body.length == 0) badRequest("body_required", "A JSON request body is required.");

        JsonNode root;
        try {
            root = objectMapper.readTree(new String(body, StandardCharsets.UTF_8));
        } catch (RuntimeException exception) {
            badRequest("invalid_json", "The request body must be valid JSON.");
            return;
        }
        if (!root.isObject()) badRequest("invalid_json", "The request body must be a JSON object.");
        root.propertyNames().forEach(field -> {
            if (!allowedFields.contains(field)) badRequest("unexpected_field", "Unsupported request field: " + field);
        });

        validateSymbol(text(root, "symbol"), true);
        if ("/market/agent".equals(path)) validateText(text(root, "message"), "message", 2, 3_000);
        if ("/market/documents/ask".equals(path)) validateText(text(root, "question"), "question", 3, 1_200);
        JsonNode recentMessages = root.get("recentMessages");
        if (recentMessages != null && (!recentMessages.isArray() || recentMessages.size() > 8)) {
            badRequest("invalid_recent_messages", "At most eight recent messages are accepted.");
        }
    }

    private void validateCommonQuery(MultiValueMap<String, String> query) {
        String symbol = query.getFirst("symbol");
        if (symbol != null) validateSymbol(symbol, true);
        String limit = query.getFirst("limit");
        if (limit != null) {
            try {
                int parsed = Integer.parseInt(limit);
                if (parsed < 1 || parsed > 100) throw new NumberFormatException();
            } catch (NumberFormatException exception) {
                badRequest("invalid_limit", "Limit must be an integer between 1 and 100.");
            }
        }
        String refresh = query.getFirst("refresh");
        if (refresh != null && !Set.of("true", "false").contains(refresh.toLowerCase())) {
            badRequest("invalid_refresh", "Refresh must be true or false.");
        }
    }

    private void rejectUnknownQueryParameters(MultiValueMap<String, String> query, Set<String> allowed) {
        query.keySet().forEach(key -> {
            if (!allowed.contains(key)) badRequest("unexpected_query", "Unsupported query parameter: " + key);
            if (query.get(key) != null && query.get(key).size() != 1) {
                badRequest("duplicate_query", "Query parameters cannot be repeated.");
            }
        });
    }

    private void validateSymbol(String value, boolean required) {
        if (blank(value)) {
            if (required) badRequest("symbol_required", "A valid market symbol is required.");
            return;
        }
        if (!SYMBOL.matcher(value.trim()).matches()) {
            badRequest("invalid_symbol", "The market symbol format is invalid.");
        }
    }

    private void validateText(String value, String field, int minimum, int maximum) {
        int length = value == null ? 0 : value.trim().length();
        if (length < minimum || length > maximum) {
            badRequest("invalid_" + field, field + " must contain between " + minimum + " and " + maximum + " characters.");
        }
    }

    private static String text(JsonNode root, String field) {
        JsonNode node = root.get(field);
        return node != null && node.isString() ? node.asString() : null;
    }

    private static boolean blank(String value) {
        return value == null || value.isBlank();
    }

    private static void badRequest(String code, String message) {
        throw new GatewayRequestException(HttpStatus.BAD_REQUEST, code, message);
    }

    private static void notFound() {
        throw new GatewayRequestException(HttpStatus.NOT_FOUND, "route_not_found", "This public gateway route is not available.");
    }
}
