package framework;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.ObjectMapper;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.regex.Pattern;

/** Central recursive and text redaction used before every diagnostic/report boundary. */
public final class SecretRedactor {
    public static final String REDACTED = "[REDACTED]";
    private static final ObjectMapper JSON = new ObjectMapper();
    private static final Pattern NAMED_SECRET = Pattern.compile(
            "(?i)(authorization|cookie|set-cookie|api[-_]?key|access[-_]?token|refresh[-_]?token|password|secret|credential|session[-_]?id)(\\s*[=:]\\s*|\\\"\\s*:\\s*\\\")([^,;\\s\\\"}]+)");
    private static final Pattern BEARER = Pattern.compile("(?i)Bearer\\s+[A-Za-z0-9._~+\\-/=]+");

    private SecretRedactor() {}

    public static Object redactObject(Object value) {
        if (value instanceof Map<?, ?> map) {
            Map<String, Object> clean = new LinkedHashMap<>();
            map.forEach((key, child) -> {
                String name = String.valueOf(key);
                clean.put(name, sensitive(name) ? REDACTED : redactObject(child));
            });
            return clean;
        }
        if (value instanceof List<?> list) {
            List<Object> clean = new ArrayList<>();
            list.forEach(child -> clean.add(redactObject(child)));
            return clean;
        }
        if (value instanceof String text) return redactText(text);
        return value;
    }

    public static String redactText(String text) {
        if (text == null) return null;
        String trimmed = text.trim();
        if ((trimmed.startsWith("{") && trimmed.endsWith("}")) || (trimmed.startsWith("[") && trimmed.endsWith("]"))) {
            try {
                Object parsed = JSON.readValue(trimmed, Object.class);
                return JSON.writeValueAsString(redactObject(parsed));
            } catch (JsonProcessingException ignored) {
                // Fall through to defensive text patterns.
            }
        }
        return redactTextWithoutJson(text);
    }

    public static boolean sensitive(String name) {
        String normalized = name.toLowerCase(Locale.ROOT).replace("-", "").replace("_", "");
        return normalized.contains("token") || normalized.contains("key") || normalized.contains("secret")
                || normalized.contains("password") || normalized.contains("authorization")
                || normalized.contains("credential") || normalized.contains("cookie")
                || normalized.contains("sessionid") || normalized.equals("username");
    }

    private static String redactTextWithoutJson(String text) {
        String bearerClean = BEARER.matcher(text).replaceAll("Bearer " + REDACTED);
        return NAMED_SECRET.matcher(bearerClean).replaceAll("$1$2" + REDACTED);
    }
}
