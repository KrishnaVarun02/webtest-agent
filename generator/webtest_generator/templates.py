"""Stable templates for the reusable generated Java framework.

The strings in this module deliberately contain no application-specific endpoints,
payloads, credentials, or assertions. Scenario-specific material is emitted by
``generator.py`` from the approved plan.
"""

from __future__ import annotations


POM_XML = """<?xml version="1.0" encoding="UTF-8"?>
<project xmlns="http://maven.apache.org/POM/4.0.0"
         xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
         xsi:schemaLocation="http://maven.apache.org/POM/4.0.0 https://maven.apache.org/xsd/maven-4.0.0.xsd">
  <modelVersion>4.0.0</modelVersion>
  <groupId>dev.webtestagent.generated</groupId>
  <artifactId>__ARTIFACT_ID__</artifactId>
  <version>1.0.0</version>
  <name>__PROJECT_NAME__</name>

  <properties>
    <maven.compiler.release>21</maven.compiler.release>
    <project.build.sourceEncoding>UTF-8</project.build.sourceEncoding>
    <testng.version>7.12.0</testng.version>
    <rest-assured.version>6.0.1</rest-assured.version>
    <jackson.version>2.22.2</jackson.version>
    <awaitility.version>4.3.0</awaitility.version>
    <extentreports.version>5.1.2</extentreports.version>
    <webtest.excludedGroups>destructive</webtest.excludedGroups>
  </properties>

  <dependencies>
    <dependency>
      <groupId>org.testng</groupId>
      <artifactId>testng</artifactId>
      <version>${testng.version}</version>
      <scope>test</scope>
    </dependency>
    <dependency>
      <groupId>io.rest-assured</groupId>
      <artifactId>rest-assured</artifactId>
      <version>${rest-assured.version}</version>
      <scope>test</scope>
    </dependency>
    <dependency>
      <groupId>com.fasterxml.jackson.core</groupId>
      <artifactId>jackson-databind</artifactId>
      <version>${jackson.version}</version>
      <scope>test</scope>
    </dependency>
    <dependency>
      <groupId>org.awaitility</groupId>
      <artifactId>awaitility</artifactId>
      <version>${awaitility.version}</version>
      <scope>test</scope>
    </dependency>
    <dependency>
      <groupId>com.aventstack</groupId>
      <artifactId>extentreports</artifactId>
      <version>${extentreports.version}</version>
      <scope>test</scope>
    </dependency>
  </dependencies>

  <build>
    <plugins>
      <plugin>
        <groupId>org.apache.maven.plugins</groupId>
        <artifactId>maven-compiler-plugin</artifactId>
        <version>3.14.1</version>
        <configuration>
          <release>21</release>
        </configuration>
      </plugin>
      <plugin>
        <groupId>org.apache.maven.plugins</groupId>
        <artifactId>maven-surefire-plugin</artifactId>
        <version>3.6.0</version>
        <configuration>
          <!-- Surefire 3.6 uses its unified JUnit Platform provider for TestNG
               and no longer consumes suiteXmlFiles. testng.xml remains usable
               with the direct TestNG runner. -->
          <includes>
            <include>**/*Test.java</include>
          </includes>
          <excludedGroups>${webtest.excludedGroups}</excludedGroups>
          <trimStackTrace>false</trimStackTrace>
          <useFile>false</useFile>
          <reportsDirectory>${project.build.directory}/surefire-reports</reportsDirectory>
        </configuration>
      </plugin>
    </plugins>
  </build>
</project>
"""


TESTNG_XML = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE suite SYSTEM "https://testng.org/testng-1.0.dtd">
<suite name="WebTest Agent generated suite" verbose="1" parallel="false">
  <listeners>
    <listener class-name="generated.listeners.WebTestReportListener"/>
  </listeners>
  <test name="approved scenarios">
    <groups>
      <run>
        <exclude name="destructive"/>
      </run>
    </groups>
    <packages>
      <package name="generated.scenarios"/>
    </packages>
  </test>
</suite>
"""


CONFIG_JAVA = r'''package framework;

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
'''


REQUEST_DEFINITION_JAVA = r'''package framework;

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
'''


AUTH_PROVIDER_JAVA = r'''package framework;

import io.restassured.specification.RequestSpecification;

/** Applies authentication without exposing its value to generated source or reports. */
@FunctionalInterface
public interface AuthProvider {
    void apply(RequestSpecification request);
}
'''


NO_AUTH_PROVIDER_JAVA = r'''package framework;

import io.restassured.specification.RequestSpecification;

public final class NoAuthProvider implements AuthProvider {
    @Override public void apply(RequestSpecification request) {
        // Intentionally unauthenticated.
    }
}
'''


BEARER_AUTH_PROVIDER_JAVA = r'''package framework;

import io.restassured.specification.RequestSpecification;
import java.util.Objects;
import java.util.function.Supplier;

public final class BearerTokenAuthProvider implements AuthProvider {
    private final Supplier<String> tokenSupplier;

    public BearerTokenAuthProvider(String environmentVariable) {
        this(() -> Config.required(environmentVariable));
    }

    private BearerTokenAuthProvider(Supplier<String> tokenSupplier) {
        this.tokenSupplier = Objects.requireNonNull(tokenSupplier);
    }

    public static BearerTokenAuthProvider fromContext(ScenarioContext context, String variable) {
        return new BearerTokenAuthProvider(() -> String.valueOf(context.require(variable)));
    }

    @Override public void apply(RequestSpecification request) {
        request.header("Authorization", "Bearer " + tokenSupplier.get());
    }
}
'''


BASIC_AUTH_PROVIDER_JAVA = r'''package framework;

import io.restassured.specification.RequestSpecification;

public final class BasicAuthProvider implements AuthProvider {
    private final String usernameVariable;
    private final String passwordVariable;

    public BasicAuthProvider(String usernameVariable, String passwordVariable) {
        this.usernameVariable = usernameVariable;
        this.passwordVariable = passwordVariable;
    }

    @Override public void apply(RequestSpecification request) {
        request.auth().preemptive().basic(Config.required(usernameVariable), Config.required(passwordVariable));
    }
}
'''


API_KEY_AUTH_PROVIDER_JAVA = r'''package framework;

import io.restassured.specification.RequestSpecification;
import java.util.Locale;

public final class ApiKeyAuthProvider implements AuthProvider {
    public enum Location { HEADER, QUERY }

    private final String valueVariable;
    private final String parameterName;
    private final Location location;

    public ApiKeyAuthProvider(String valueVariable, String parameterName, Location location) {
        this.valueVariable = valueVariable;
        this.parameterName = parameterName;
        this.location = location;
    }

    public static Location location(String raw) {
        return Location.valueOf(raw.trim().toUpperCase(Locale.ROOT));
    }

    @Override public void apply(RequestSpecification request) {
        String value = Config.required(valueVariable);
        if (location == Location.HEADER) request.header(parameterName, value);
        else request.queryParam(parameterName, value);
    }
}
'''


COOKIE_AUTH_PROVIDER_JAVA = r'''package framework;

import io.restassured.specification.RequestSpecification;

public final class CookieAuthProvider implements AuthProvider {
    private final String valueVariable;
    private final String cookieName;

    public CookieAuthProvider(String valueVariable, String cookieName) {
        this.valueVariable = valueVariable;
        this.cookieName = cookieName;
    }

    @Override public void apply(RequestSpecification request) {
        request.cookie(cookieName, Config.required(valueVariable));
    }
}
'''


CUSTOM_AUTH_PROVIDER_JAVA = r'''package framework;

/** Extension hook for an application-specific auth handshake; keep all secrets in environment variables. */
public abstract class CustomAuthProvider implements AuthProvider {
    protected final String requireEnvironment(String name) {
        return Config.required(name);
    }
}
'''


AUTH_PROVIDERS_JAVA = r'''package framework;

import java.util.Locale;

/** Selects common authentication adapters entirely from environment configuration. */
public final class AuthProviders {
    private AuthProviders() {}

    public static AuthProvider fromEnvironment(Config config, ScenarioContext context, String bearerContextVariable) {
        String type = System.getenv().getOrDefault("WEBTEST_AUTH_TYPE", "").trim().toLowerCase(Locale.ROOT);
        if (type.isEmpty() && bearerContextVariable != null && context.contains(bearerContextVariable)) {
            return BearerTokenAuthProvider.fromContext(context, bearerContextVariable);
        }
        return switch (type) {
            case "", "none" -> new NoAuthProvider();
            case "bearer" -> new BearerTokenAuthProvider(
                    System.getenv().getOrDefault("WEBTEST_BEARER_TOKEN_ENV", "API_TOKEN"));
            case "basic" -> new BasicAuthProvider(
                    System.getenv().getOrDefault("WEBTEST_BASIC_USERNAME_ENV", "TEST_USERNAME"),
                    System.getenv().getOrDefault("WEBTEST_BASIC_PASSWORD_ENV", "TEST_PASSWORD"));
            case "api_key" -> new ApiKeyAuthProvider(
                    System.getenv().getOrDefault("WEBTEST_API_KEY_VALUE_ENV", "API_KEY"),
                    Config.required("WEBTEST_API_KEY_NAME"),
                    ApiKeyAuthProvider.location(System.getenv().getOrDefault("WEBTEST_API_KEY_LOCATION", "header")));
            case "cookie" -> new CookieAuthProvider(
                    System.getenv().getOrDefault("WEBTEST_COOKIE_VALUE_ENV", "TEST_COOKIE"),
                    Config.required("WEBTEST_COOKIE_NAME"));
            default -> throw new IllegalStateException("unsupported WEBTEST_AUTH_TYPE: " + type);
        };
    }
}
'''


SCENARIO_CONTEXT_JAVA = r'''package framework;

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
'''


DYNAMIC_EXTRACTOR_JAVA = r'''package framework;

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
'''


TEST_DATA_FACTORY_JAVA = r'''package framework;

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
'''


POLLING_UTILITY_JAVA = r'''package framework;

import io.restassured.response.Response;
import java.time.Duration;
import java.util.ArrayList;
import java.util.List;
import java.util.concurrent.atomic.AtomicReference;
import java.util.function.Predicate;
import java.util.function.Supplier;
import org.awaitility.core.ConditionTimeoutException;

import static org.awaitility.Awaitility.await;

/** Bounded asynchronous polling with a sanitized observation history. */
public final class PollingUtility {
    private PollingUtility() {}

    public static Response poll(
            String stepName,
            Supplier<Response> request,
            Predicate<Response> completed,
            Duration timeout,
            Duration interval) {
        if (timeout.isZero() || timeout.isNegative() || interval.isZero() || interval.isNegative()) {
            throw new IllegalArgumentException("poll timeout and interval must be positive");
        }
        AtomicReference<Response> latest = new AtomicReference<>();
        List<String> history = new ArrayList<>();
        try {
            await(stepName).pollInterval(interval).atMost(timeout).until(() -> {
                Response response = request.get();
                latest.set(response);
                String observation = "status=" + response.statusCode() + ", body="
                        + SecretRedactor.redactText(response.asString());
                history.add(observation);
                ExecutionTrace.recordPolling(stepName, observation);
                return completed.test(response);
            });
        } catch (ConditionTimeoutException timeoutException) {
            throw new AssertionError("polling timed out for " + stepName + "; observations=" + history, timeoutException);
        }
        return latest.get();
    }
}
'''


ASSERTION_UTILITY_JAVA = r'''package framework;

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
'''


SECRET_REDACTOR_JAVA = r'''package framework;

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
'''


EXECUTION_TRACE_JAVA = r'''package framework;

import java.util.ArrayList;
import java.util.List;

/** Thread-local structured details consumed by the HTML report listener. */
public final class ExecutionTrace {
    public record Event(String kind, String detail) {}
    private static final ThreadLocal<List<Event>> EVENTS = ThreadLocal.withInitial(ArrayList::new);

    private ExecutionTrace() {}

    public static void start() { EVENTS.get().clear(); }

    public static void recordStep(String name, Object request, Object response, long elapsedMillis) {
        String detail = "step=" + name + "\nrequest=" + SecretRedactor.redactText(String.valueOf(request))
                + "\nresponse=" + SecretRedactor.redactText(String.valueOf(response))
                + "\nelapsedMs=" + elapsedMillis;
        EVENTS.get().add(new Event("step", detail));
    }

    public static void recordExtraction(String variable, Object value) {
        Object safe = SecretRedactor.sensitive(variable) ? SecretRedactor.REDACTED : SecretRedactor.redactObject(value);
        EVENTS.get().add(new Event("extracted variable", variable + "=" + safe));
    }

    public static void recordPolling(String step, String observation) {
        EVENTS.get().add(new Event("poll", step + ": " + SecretRedactor.redactText(observation)));
    }

    public static void recordAssertion(String assertion, Object expected, Object actual) {
        String detail = assertion + "\nexpected=" + SecretRedactor.redactText(String.valueOf(SecretRedactor.redactObject(expected)))
                + "\nactual=" + SecretRedactor.redactText(String.valueOf(SecretRedactor.redactObject(actual)));
        EVENTS.get().add(new Event("assertion", detail));
    }

    public static void note(String note) {
        EVENTS.get().add(new Event("note", SecretRedactor.redactText(note)));
    }

    public static List<Event> drain() {
        List<Event> copy = List.copyOf(EVENTS.get());
        EVENTS.remove();
        return copy;
    }
}
'''


REQUEST_EXECUTOR_JAVA = r'''package framework;

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
'''


GENERATED_API_CLIENT_JAVA = r'''package generated.clients;

import framework.AuthProvider;
import framework.Config;
import framework.RequestDefinition;
import framework.RequestExecutor;
import framework.ScenarioContext;
import io.restassured.response.Response;

/** Thin generated-facing client; endpoint behavior remains in approved scenario data. */
public final class GeneratedApiClient {
    private final RequestExecutor executor;

    public GeneratedApiClient(Config config) {
        this.executor = new RequestExecutor(config);
    }

    public Response execute(String stepName, RequestDefinition request, ScenarioContext context, AuthProvider auth) {
        return executor.execute(stepName, request, context, auth);
    }
}
'''


REPORT_LISTENER_JAVA = r'''package generated.listeners;

import com.aventstack.extentreports.ExtentReports;
import com.aventstack.extentreports.ExtentTest;
import com.aventstack.extentreports.reporter.ExtentSparkReporter;
import framework.ExecutionTrace;
import framework.SecretRedactor;
import java.io.PrintWriter;
import java.io.StringWriter;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;
import org.testng.ISuite;
import org.testng.ISuiteListener;
import org.testng.ITestListener;
import org.testng.ITestResult;

/** Extent/TestNG listener. Every value crosses SecretRedactor before reaching HTML. */
public final class WebTestReportListener implements ITestListener, ISuiteListener {
    private static final Map<ITestResult, ExtentTest> TESTS = new ConcurrentHashMap<>();
    private static ExtentReports reports;

    private static synchronized ExtentReports reports() {
        if (reports == null) {
            try {
                Path directory = Path.of("target", "webtest-report");
                Files.createDirectories(directory);
                ExtentSparkReporter reporter = new ExtentSparkReporter(directory.resolve("index.html").toString());
                reporter.config().setDocumentTitle("WebTest Agent execution report");
                reporter.config().setReportName("Authorized API scenarios");
                reports = new ExtentReports();
                reports.attachReporter(reporter);
                reports.setSystemInfo("environment", SecretRedactor.redactText(
                        System.getenv().getOrDefault("WEBTEST_ENVIRONMENT", "unspecified")));
            } catch (Exception exception) {
                throw new IllegalStateException("unable to initialize sanitized HTML report", exception);
            }
        }
        return reports;
    }

    @Override public void onTestStart(ITestResult result) {
        ExecutionTrace.start();
        TESTS.put(result, reports().createTest(result.getTestClass().getName() + "." + result.getMethod().getMethodName()));
    }

    @Override public void onTestSuccess(ITestResult result) { finish(result, "PASS", null); }
    @Override public void onTestFailure(ITestResult result) { finish(result, "FAIL", result.getThrowable()); }
    @Override public void onTestSkipped(ITestResult result) { finish(result, "SKIP", result.getThrowable()); }

    private static void finish(ITestResult result, String outcome, Throwable failure) {
        ExtentTest test = TESTS.remove(result);
        if (test == null) test = reports().createTest(result.getMethod().getMethodName());
        for (ExecutionTrace.Event event : ExecutionTrace.drain()) {
            test.info(SecretRedactor.redactText(event.kind() + "\n" + event.detail()));
        }
        test.info("elapsedMs=" + Math.max(0L, result.getEndMillis() - result.getStartMillis()));
        if (outcome.equals("PASS")) test.pass("passed");
        else if (outcome.equals("SKIP")) test.skip(failure == null ? "skipped" : stack(failure));
        else test.fail(failure == null ? "failed" : stack(failure));
    }

    private static String stack(Throwable throwable) {
        StringWriter output = new StringWriter();
        throwable.printStackTrace(new PrintWriter(output));
        return SecretRedactor.redactText(output.toString());
    }

    @Override public synchronized void onFinish(ISuite suite) {
        if (reports != null) reports.flush();
    }
}
'''


FRAMEWORK_FILES = {
    "Config.java": CONFIG_JAVA,
    "RequestExecutor.java": REQUEST_EXECUTOR_JAVA,
    "RequestDefinition.java": REQUEST_DEFINITION_JAVA,
    "AuthProvider.java": AUTH_PROVIDER_JAVA,
    "NoAuthProvider.java": NO_AUTH_PROVIDER_JAVA,
    "BearerTokenAuthProvider.java": BEARER_AUTH_PROVIDER_JAVA,
    "BasicAuthProvider.java": BASIC_AUTH_PROVIDER_JAVA,
    "ApiKeyAuthProvider.java": API_KEY_AUTH_PROVIDER_JAVA,
    "CookieAuthProvider.java": COOKIE_AUTH_PROVIDER_JAVA,
    "CustomAuthProvider.java": CUSTOM_AUTH_PROVIDER_JAVA,
    "AuthProviders.java": AUTH_PROVIDERS_JAVA,
    "ScenarioContext.java": SCENARIO_CONTEXT_JAVA,
    "DynamicValueExtractor.java": DYNAMIC_EXTRACTOR_JAVA,
    "TestDataFactory.java": TEST_DATA_FACTORY_JAVA,
    "PollingUtility.java": POLLING_UTILITY_JAVA,
    "AssertionUtility.java": ASSERTION_UTILITY_JAVA,
    "SecretRedactor.java": SECRET_REDACTOR_JAVA,
    "ExecutionTrace.java": EXECUTION_TRACE_JAVA,
}


def pom_xml(project_name: str) -> str:
    return POM_XML.replace("__ARTIFACT_ID__", project_name).replace("__PROJECT_NAME__", project_name)
