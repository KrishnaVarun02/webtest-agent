package framework;

import io.restassured.response.Response;

public final class DynamicValueExtractor {
    private DynamicValueExtractor() {}

    public static Object extract(Response response, String jsonPath, ScenarioContext context, String variable) {
        String normalized = jsonPath != null && jsonPath.startsWith("$.") ? jsonPath.substring(2) : jsonPath;
        Object value = response.jsonPath().get(normalized);
        if (value == null) throw new AssertionError("required extracted value was absent at " + jsonPath);
        context.put(variable, value);
        ExecutionTrace.recordExtraction(variable, value);
        return value;
    }
}
