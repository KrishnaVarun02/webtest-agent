package framework;

import java.util.Collections;
import java.util.LinkedHashMap;
import java.util.Locale;
import java.util.Map;

/** Immutable, data-oriented HTTP request description. */
public final class RequestDefinition {
    private final String method;
    private final String path;
    private final Map<String, String> headers;
    private final Map<String, Object> query;
    private final Object body;
    private final String contentType;

    private RequestDefinition(Builder builder) {
        this.method = builder.method.toUpperCase(Locale.ROOT);
        this.path = builder.path;
        this.headers = Collections.unmodifiableMap(new LinkedHashMap<>(builder.headers));
        this.query = Collections.unmodifiableMap(new LinkedHashMap<>(builder.query));
        this.body = builder.body;
        this.contentType = builder.contentType;
    }

    public static Builder builder(String method, String path) {
        return new Builder(method, path);
    }

    public String method() { return method; }
    public String path() { return path; }
    public Map<String, String> headers() { return headers; }
    public Map<String, Object> query() { return query; }
    public Object body() { return body; }
    public String contentType() { return contentType; }

    public static final class Builder {
        private final String method;
        private final String path;
        private final Map<String, String> headers = new LinkedHashMap<>();
        private final Map<String, Object> query = new LinkedHashMap<>();
        private Object body;
        private String contentType = "application/json";

        private Builder(String method, String path) {
            if (method == null || method.isBlank() || path == null || path.isBlank()) {
                throw new IllegalArgumentException("method and path are required");
            }
            this.method = method;
            this.path = path;
        }

        public Builder header(String name, String value) { headers.put(name, value); return this; }
        public Builder query(String name, Object value) { query.put(name, value); return this; }
        public Builder body(Object value) { body = value; return this; }
        public Builder contentType(String value) { contentType = value; return this; }
        public RequestDefinition build() { return new RequestDefinition(this); }
    }
}
