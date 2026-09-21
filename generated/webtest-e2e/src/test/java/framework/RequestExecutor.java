package framework;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.ObjectMapper;
import io.restassured.RestAssured;
import io.restassured.response.Response;
import io.restassured.specification.RequestSpecification;
import java.util.LinkedHashMap;
import java.util.Map;

/** Executes one authorized-origin-relative request and records only sanitized diagnostics. */
public final class RequestExecutor {
    private static final ObjectMapper JSON = new ObjectMapper();
    private final Config config;

    public RequestExecutor(Config config) {
        this.config = config;
    }

    public Response execute(String stepName, RequestDefinition definition, ScenarioContext context, AuthProvider auth) {
        String path = context.resolve(definition.path());
        config.validateRelativeRequestPath(path);
        @SuppressWarnings("unchecked")
        Map<String, String> headers = (Map<String, String>) context.resolveObject(definition.headers());
        @SuppressWarnings("unchecked")
        Map<String, Object> query = (Map<String, Object>) context.resolveObject(definition.query());
        Object body = context.resolveObject(definition.body());

        RequestSpecification request = RestAssured.given().baseUri(config.baseUri().toString());
        if (!headers.isEmpty()) request.headers(headers);
        if (!query.isEmpty()) request.queryParams(query);
        if (definition.contentType() != null && !definition.contentType().isBlank()) request.contentType(definition.contentType());
        if (body != null) request.body(body);
        auth.apply(request);

        Map<String, Object> diagnosticRequest = new LinkedHashMap<>();
        diagnosticRequest.put("method", definition.method());
        diagnosticRequest.put("path", path);
        diagnosticRequest.put("headers", headers);
        diagnosticRequest.put("query", query);
        diagnosticRequest.put("body", body);

        long started = System.nanoTime();
        Response response = request.request(definition.method(), path);
        long elapsedMillis = (System.nanoTime() - started) / 1_000_000L;
        Map<String, Object> diagnosticResponse = new LinkedHashMap<>();
        diagnosticResponse.put("status", response.statusCode());
        diagnosticResponse.put("headers", response.headers().asList().stream()
                .collect(LinkedHashMap::new, (map, header) -> map.put(header.getName(), header.getValue()), Map::putAll));
        diagnosticResponse.put("body", response.asString());
        ExecutionTrace.recordStep(stepName, toJson(SecretRedactor.redactObject(diagnosticRequest)),
                toJson(SecretRedactor.redactObject(diagnosticResponse)), elapsedMillis);
        return response;
    }

    private static String toJson(Object value) {
        try {
            return JSON.writeValueAsString(value);
        } catch (JsonProcessingException exception) {
            return SecretRedactor.redactText(String.valueOf(value));
        }
    }
}
