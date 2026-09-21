package framework;

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
