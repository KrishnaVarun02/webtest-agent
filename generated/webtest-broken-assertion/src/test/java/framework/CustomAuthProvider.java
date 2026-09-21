package framework;

/** Extension hook for an application-specific auth handshake; keep all secrets in environment variables. */
public abstract class CustomAuthProvider implements AuthProvider {
    protected final String requireEnvironment(String name) {
        return Config.required(name);
    }
}
