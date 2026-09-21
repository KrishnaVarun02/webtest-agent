package framework;

import io.restassured.specification.RequestSpecification;

/** Applies authentication without exposing its value to generated source or reports. */
@FunctionalInterface
public interface AuthProvider {
    void apply(RequestSpecification request);
}
