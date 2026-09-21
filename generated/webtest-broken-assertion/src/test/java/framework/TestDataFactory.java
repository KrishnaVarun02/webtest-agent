package framework;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.ObjectMapper;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.UUID;

/** JSON parsing, deep copies, and evidence-preserving one-field negative mutations. */
public final class TestDataFactory {
    private static final ObjectMapper JSON = new ObjectMapper();
    private TestDataFactory() {}

    public static Object json(String value) { return parse(value); }
    public static Object value(String value) { return parse(value); }

    public static Object deepCopy(Object value) {
        return JSON.convertValue(value, Object.class);
    }

    public static Object removePath(Object valid, String dottedPath) {
        Object copy = deepCopy(valid);
        Map<String, Object> parent = parentMap(copy, dottedPath);
        String leaf = leaf(dottedPath);
        if (!parent.containsKey(leaf)) throw new IllegalArgumentException("mutation path not found: " + dottedPath);
        parent.remove(leaf);
        return copy;
    }

    public static Object replacePath(Object valid, String dottedPath, Object replacement) {
        Object copy = deepCopy(valid);
        Map<String, Object> parent = parentMap(copy, dottedPath);
        String leaf = leaf(dottedPath);
        if (!parent.containsKey(leaf)) throw new IllegalArgumentException("mutation path not found: " + dottedPath);
        parent.put(leaf, replacement);
        return copy;
    }

    public static String nonexistentUuid() {
        return UUID.randomUUID().toString();
    }

    @SuppressWarnings("unchecked")
    private static Map<String, Object> parentMap(Object value, String dottedPath) {
        if (!(value instanceof Map<?, ?>)) throw new IllegalArgumentException("body mutation requires a JSON object");
        String[] parts = dottedPath.replaceFirst("^\\$\\.?", "").split("\\.");
        Map<String, Object> current = (Map<String, Object>) value;
        for (int index = 0; index < parts.length - 1; index++) {
            Object child = current.get(parts[index]);
            if (!(child instanceof Map<?, ?>)) throw new IllegalArgumentException("mutation path not found: " + dottedPath);
            current = (Map<String, Object>) child;
        }
        return current;
    }

    private static String leaf(String path) {
        String normalized = path.replaceFirst("^\\$\\.?", "");
        int separator = normalized.lastIndexOf('.');
        return separator < 0 ? normalized : normalized.substring(separator + 1);
    }

    private static Object parse(String value) {
        try {
            return JSON.readValue(value, Object.class);
        } catch (JsonProcessingException exception) {
            throw new IllegalArgumentException("generated JSON fixture is invalid", exception);
        }
    }
}
