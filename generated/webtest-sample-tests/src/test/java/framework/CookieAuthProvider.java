package framework;

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
