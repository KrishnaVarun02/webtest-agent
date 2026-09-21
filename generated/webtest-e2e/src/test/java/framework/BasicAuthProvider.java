package framework;

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
