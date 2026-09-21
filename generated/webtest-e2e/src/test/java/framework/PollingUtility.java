package framework;

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
