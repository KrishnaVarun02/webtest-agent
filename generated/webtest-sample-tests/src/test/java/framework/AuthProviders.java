package framework;

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
