package framework;

import java.net.URI;
import java.util.Arrays;
import java.util.LinkedHashSet;
import java.util.Locale;
import java.util.Set;
import java.util.stream.Collectors;
import org.testng.SkipException;

/** Environment-only runtime configuration with an explicit origin boundary. */
public final class Config {
    private static final Set<String> NON_PRODUCTION = Set.of(
            "local", "test", "testing", "qa", "staging", "development", "dev", "non-production");

    private final URI baseUri;
    private final Set<String> authorizedOrigins;
    private final String environment;

    private Config(URI baseUri, Set<String> authorizedOrigins, String environment) {
        this.baseUri = baseUri;
        this.authorizedOrigins = Set.copyOf(authorizedOrigins);
        this.environment = environment;
        validateAuthorizedOrigin();
    }

    public static Config fromEnvironment() {
        URI base = parseHttpUri(required("WEBTEST_BASE_URL"), "WEBTEST_BASE_URL");
        Set<String> origins = Arrays.stream(required("WEBTEST_AUTHORIZED_ORIGINS").split(","))
                .map(String::trim)
                .filter(value -> !value.isEmpty())
                .map(value -> origin(parseHttpUri(value, "WEBTEST_AUTHORIZED_ORIGINS")))
                .collect(Collectors.toCollection(LinkedHashSet::new));
        if (origins.isEmpty()) {
            throw new IllegalStateException("WEBTEST_AUTHORIZED_ORIGINS must contain at least one origin");
        }
        String environment = System.getenv().getOrDefault("WEBTEST_ENVIRONMENT", "unspecified")
                .trim().toLowerCase(Locale.ROOT);
        if (!NON_PRODUCTION.contains(environment)) {
            System.err.println("WARNING: WEBTEST_ENVIRONMENT is not an explicit non-production value; negative tests will skip.");
        }
        return new Config(base, origins, environment);
    }

    public URI baseUri() {
        return baseUri;
    }

    public String environment() {
        return environment;
    }

    public int pollTimeoutSeconds() {
        return positiveInt("WEBTEST_POLL_TIMEOUT_SECONDS", 10);
    }

    public int pollIntervalMillis() {
        return positiveInt("WEBTEST_POLL_INTERVAL_MILLIS", 200);
    }

    public void requireNegativeTestEnvironment() {
        if (!NON_PRODUCTION.contains(environment)) {
            throw new SkipException("Negative tests require WEBTEST_ENVIRONMENT=local/test/qa/staging/development");
        }
    }

    public void requireDestructiveOptIn() {
        if (!Boolean.parseBoolean(System.getenv().getOrDefault("ALLOW_DESTRUCTIVE_TESTS", "false"))) {
            throw new SkipException("Destructive test disabled; set ALLOW_DESTRUCTIVE_TESTS=true to opt in");
        }
    }

    public void validateRelativeRequestPath(String path) {
        if (path == null || path.isBlank() || !path.startsWith("/")) {
            throw new IllegalArgumentException("generated request paths must be non-empty and origin-relative");
        }
        URI candidate = URI.create(path);
        if (candidate.isAbsolute() || candidate.getHost() != null || path.startsWith("//")) {
            throw new SecurityException("cross-origin request rejected: " + SecretRedactor.redactText(path));
        }
    }

    private void validateAuthorizedOrigin() {
        String configuredOrigin = origin(baseUri);
        if (!authorizedOrigins.contains(configuredOrigin)) {
            throw new SecurityException("configured base URL origin is not in WEBTEST_AUTHORIZED_ORIGINS");
        }
    }

    private static URI parseHttpUri(String raw, String variable) {
        URI uri;
        try {
            uri = URI.create(raw);
        } catch (IllegalArgumentException exception) {
            throw new IllegalStateException(variable + " is not a valid URI", exception);
        }
        String scheme = uri.getScheme() == null ? "" : uri.getScheme().toLowerCase(Locale.ROOT);
        if (!(scheme.equals("http") || scheme.equals("https")) || uri.getHost() == null || uri.getUserInfo() != null) {
            throw new IllegalStateException(variable + " must be an http(s) URL without user info");
        }
        return uri;
    }

    private static String origin(URI uri) {
        String scheme = uri.getScheme().toLowerCase(Locale.ROOT);
        String host = uri.getHost().toLowerCase(Locale.ROOT);
        int port = uri.getPort();
        boolean defaultPort = port == -1 || (scheme.equals("http") && port == 80) || (scheme.equals("https") && port == 443);
        return scheme + "://" + host + (defaultPort ? "" : ":" + port);
    }

    static String required(String name) {
        String value = System.getenv(name);
        if (value == null || value.isBlank()) {
            throw new IllegalStateException("required environment variable is missing: " + name);
        }
        return value;
    }

    private static int positiveInt(String name, int fallback) {
        String raw = System.getenv(name);
        if (raw == null || raw.isBlank()) {
            return fallback;
        }
        try {
            int parsed = Integer.parseInt(raw);
            if (parsed <= 0) throw new NumberFormatException("not positive");
            return parsed;
        } catch (NumberFormatException exception) {
            throw new IllegalStateException(name + " must be a positive integer", exception);
        }
    }
}
