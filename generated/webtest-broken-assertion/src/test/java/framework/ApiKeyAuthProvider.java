package framework;

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
