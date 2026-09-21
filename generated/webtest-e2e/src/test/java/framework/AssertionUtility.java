package framework;

import io.restassured.response.Response;
import java.time.Instant;
import java.time.format.DateTimeParseException;
import java.util.List;
import java.util.Objects;
import java.util.UUID;

/** Focused assertions that avoid brittle whole-response comparisons. */
public final class AssertionUtility {
    private AssertionUtility() {}

    public static void assertStatus(Response response, int expected) {
        ExecutionTrace.recordAssertion("HTTP status", expected, response.statusCode());
        if (response.statusCode() != expected) {
            throw new AssertionError("expected HTTP " + expected + " but got " + response.statusCode()
                    + "; response=" + SecretRedactor.redactText(response.asString()));
        }
    }

    public static void assertContentType(Response response, String expectedPrefix) {
        String actual = response.contentType() == null ? "" : response.contentType();
        ExecutionTrace.recordAssertion("content type", expectedPrefix, actual);
        if (!actual.toLowerCase().startsWith(expectedPrefix.toLowerCase())) {
            throw new AssertionError("expected content type " + expectedPrefix + " but got " + actual);
        }
    }

    public static void assertRequiredFields(Response response, List<String> paths) {
        for (String path : paths) assertFieldPresent(response, path);
    }

    public static void assertFieldPresent(Response response, String jsonPath) {
        Object value = response.jsonPath().get(normalize(jsonPath));
        ExecutionTrace.recordAssertion("field present " + jsonPath, "present", value == null ? "absent" : "present");
        if (value == null) throw new AssertionError("required response field absent: " + jsonPath);
    }

    public static void assertJsonPathEquals(Response response, String jsonPath, Object expected) {
        Object actual = response.jsonPath().get(normalize(jsonPath));
        ExecutionTrace.recordAssertion("JSON value " + jsonPath, expected, actual);
        if (!Objects.equals(normalizeNumber(actual), normalizeNumber(expected))) {
            throw new AssertionError("expected " + jsonPath + "=" + SecretRedactor.redactText(String.valueOf(expected))
                    + " but got " + SecretRedactor.redactText(String.valueOf(actual)));
        }
    }

    public static void assertJsonType(Response response, String jsonPath, String expectedType) {
        Object value = response.jsonPath().get(normalize(jsonPath));
        String actualType = value == null ? "null" : value.getClass().getSimpleName();
        ExecutionTrace.recordAssertion("JSON type " + jsonPath, expectedType, actualType);
        boolean matches = switch (expectedType.toLowerCase()) {
            case "string" -> value instanceof String;
            case "integer", "int" -> value instanceof Byte || value instanceof Short || value instanceof Integer || value instanceof Long;
            case "number" -> value instanceof Number;
            case "boolean", "bool" -> value instanceof Boolean;
            case "array", "list" -> value instanceof List<?>;
            case "object", "map" -> value instanceof java.util.Map<?, ?>;
            case "null" -> value == null;
            default -> throw new IllegalArgumentException("unsupported asserted JSON type: " + expectedType);
        };
        if (!matches) throw new AssertionError("response field " + jsonPath + " was not type " + expectedType);
    }

    public static void assertFormat(Response response, String jsonPath, String format) {
        Object raw = response.jsonPath().get(normalize(jsonPath));
        ExecutionTrace.recordAssertion("format " + jsonPath, format, raw);
        if (!(raw instanceof String value)) throw new AssertionError("formatted field is not a string: " + jsonPath);
        try {
            if (format.equalsIgnoreCase("uuid")) UUID.fromString(value);
            else if (format.equalsIgnoreCase("timestamp") || format.equalsIgnoreCase("date-time")) Instant.parse(value);
            else if (format.startsWith("regex:")) {
                if (!value.matches(format.substring("regex:".length()))) throw new IllegalArgumentException("regex mismatch");
            } else throw new IllegalArgumentException("unsupported format: " + format);
        } catch (IllegalArgumentException | DateTimeParseException exception) {
            throw new AssertionError("response field " + jsonPath + " did not match format " + format, exception);
        }
    }

    private static String normalize(String path) { return path != null && path.startsWith("$.") ? path.substring(2) : path; }
    private static Object normalizeNumber(Object value) {
        if (value instanceof Number number) return number.toString();
        return value;
    }
}
