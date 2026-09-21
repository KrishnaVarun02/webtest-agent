package generated.clients;

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
