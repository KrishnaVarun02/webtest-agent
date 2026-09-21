package framework;

import io.restassured.specification.RequestSpecification;

public final class NoAuthProvider implements AuthProvider {
    @Override public void apply(RequestSpecification request) {
        // Intentionally unauthenticated.
    }
}
