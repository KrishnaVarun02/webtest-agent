package framework;

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
