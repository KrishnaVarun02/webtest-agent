package framework;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/** Per-test data flow. Values never cross scenario/thread boundaries. */
public final class ScenarioContext {
    private static final Pattern PLACEHOLDER = Pattern.compile("\\$\\{([A-Za-z_][A-Za-z0-9_.-]*)}");
    private final Map<String, Object> values = new LinkedHashMap<>();

    public void put(String name, Object value) {
        if (name == null || name.isBlank() || value == null) throw new IllegalArgumentException("context name/value required");
        values.put(name, value);
    }

    public boolean contains(String name) { return values.containsKey(name); }

    public Object require(String name) {
        if (values.containsKey(name)) return values.get(name);
        String environment = System.getenv(name);
        if (environment != null && !environment.isBlank()) return environment;
        throw new IllegalStateException("unresolved scenario/environment variable: " + name);
    }

    public String resolve(String input) {
        if (input == null) return null;
        Matcher matcher = PLACEHOLDER.matcher(input);
        StringBuffer output = new StringBuffer();
        while (matcher.find()) {
            matcher.appendReplacement(output, Matcher.quoteReplacement(String.valueOf(require(matcher.group(1)))));
        }
        matcher.appendTail(output);
        return output.toString();
    }

    public Object resolveObject(Object input) {
        if (input instanceof String text) {
            Matcher exact = PLACEHOLDER.matcher(text);
            if (exact.matches()) return require(exact.group(1));
            return resolve(text);
        }
        if (input instanceof Map<?, ?> map) {
            Map<String, Object> copy = new LinkedHashMap<>();
            map.forEach((key, value) -> copy.put(String.valueOf(key), resolveObject(value)));
            return copy;
        }
        if (input instanceof List<?> list) {
            List<Object> copy = new ArrayList<>();
            list.forEach(value -> copy.add(resolveObject(value)));
            return copy;
        }
        return input;
    }

    public Map<String, Object> sanitizedSnapshot() {
        @SuppressWarnings("unchecked")
        Map<String, Object> copy = (Map<String, Object>) SecretRedactor.redactObject(values);
        return copy;
    }
}
