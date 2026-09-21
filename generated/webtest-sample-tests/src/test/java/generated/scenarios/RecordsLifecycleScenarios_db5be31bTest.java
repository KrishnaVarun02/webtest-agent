package generated.scenarios;

import framework.*;
import generated.clients.GeneratedApiClient;
import io.restassured.response.Response;
import java.time.Duration;
import java.util.List;
import java.util.Objects;
import generated.listeners.WebTestReportListener;
import org.testng.annotations.BeforeMethod;
import org.testng.annotations.Listeners;
import org.testng.annotations.Test;

/** Generated only from approved workflow records-lifecycle. */
@Listeners(WebTestReportListener.class)
public final class RecordsLifecycleScenarios_db5be31bTest {
    private Config config;
    private GeneratedApiClient client;

    @BeforeMethod(alwaysRun = true)
    public void configure() {
        config = Config.fromEnvironment();
        client = new GeneratedApiClient(config);
    }

    private AuthProvider configuredAuth(ScenarioContext context) {
        return AuthProviders.fromEnvironment(config, context, "accessToken");
    }

    @Test(groups = {"regression", "positive", "destructive"}, enabled = true)
    public void archiveACreatedRecordWhenExplicitlyEnabled_40e51317() {
        ScenarioContext context = new ScenarioContext();
        config.requireDestructiveOptIn();
        ExecutionTrace.note("Review note: Excluded by default and guarded by ALLOW_DESTRUCTIVE_TESTS.");

        // 1. Log in with supplied test credentials
        RequestDefinition.Builder request1Builder = RequestDefinition.builder("POST", "/api/login");
        request1Builder.header("Content-Type", "application/json");
        request1Builder.contentType("application/json");
        request1Builder.body(TestDataFactory.json("{\"password\":\"${TEST_PASSWORD}\",\"username\":\"${TEST_USERNAME}\"}"));
        RequestDefinition request1 = request1Builder.build();
        AuthProvider auth1 = new NoAuthProvider();
        Response response1 = client.execute("Log in with supplied test credentials", request1, context, auth1);
        AssertionUtility.assertStatus(response1, 200);
        AssertionUtility.assertContentType(response1, "application/json");
        AssertionUtility.assertRequiredFields(response1, List.of("accessToken", "tokenType"));
        DynamicValueExtractor.extract(response1, "$.accessToken", context, "accessToken");

        // 2. Create a record
        RequestDefinition.Builder request2Builder = RequestDefinition.builder("POST", "/api/records");
        request2Builder.header("Content-Type", "application/json");
        request2Builder.contentType("application/json");
        request2Builder.body(TestDataFactory.json("{\"name\":\"Generated record\",\"quantity\":2}"));
        RequestDefinition request2 = request2Builder.build();
        AuthProvider auth2 = configuredAuth(context);
        Response response2 = client.execute("Create a record", request2, context, auth2);
        AssertionUtility.assertStatus(response2, 201);
        AssertionUtility.assertContentType(response2, "application/json");
        AssertionUtility.assertRequiredFields(response2, List.of("id", "name", "status"));
        DynamicValueExtractor.extract(response2, "$.id", context, "recordId");

        // 3. Archive the created record
        RequestDefinition.Builder request3Builder = RequestDefinition.builder("DELETE", "/api/records/${recordId}");
        request3Builder.header("X-Allow-Destructive", "true");
        request3Builder.contentType("application/json");
        RequestDefinition request3 = request3Builder.build();
        AuthProvider auth3 = configuredAuth(context);
        Response response3 = client.execute("Archive the created record", request3, context, auth3);
        AssertionUtility.assertStatus(response3, 200);
        AssertionUtility.assertContentType(response3, "application/json");
        AssertionUtility.assertRequiredFields(response3, List.of("archived", "id"));
        AssertionUtility.assertJsonPathEquals(response3, "$.archived", context.resolveObject(TestDataFactory.value("true")));
    }

    @Test(groups = {"regression", "negative"}, enabled = true)
    public void rejectACreateRequestMissingName_a8aadd19() {
        ScenarioContext context = new ScenarioContext();
        config.requireNegativeTestEnvironment();

        // 1. Log in with supplied test credentials
        RequestDefinition.Builder request1Builder = RequestDefinition.builder("POST", "/api/login");
        request1Builder.header("Content-Type", "application/json");
        request1Builder.contentType("application/json");
        request1Builder.body(TestDataFactory.json("{\"password\":\"${TEST_PASSWORD}\",\"username\":\"${TEST_USERNAME}\"}"));
        RequestDefinition request1 = request1Builder.build();
        AuthProvider auth1 = new NoAuthProvider();
        Response response1 = client.execute("Log in with supplied test credentials", request1, context, auth1);
        AssertionUtility.assertStatus(response1, 200);
        AssertionUtility.assertContentType(response1, "application/json");
        AssertionUtility.assertRequiredFields(response1, List.of("accessToken", "tokenType"));
        DynamicValueExtractor.extract(response1, "$.accessToken", context, "accessToken");

        // 2. Create a record
        RequestDefinition.Builder request2Builder = RequestDefinition.builder("POST", "/api/records");
        request2Builder.header("Content-Type", "application/json");
        request2Builder.contentType("application/json");
        request2Builder.body(TestDataFactory.json("{\"quantity\":2}"));
        RequestDefinition request2 = request2Builder.build();
        AuthProvider auth2 = configuredAuth(context);
        Response response2 = client.execute("Create a record", request2, context, auth2);
        AssertionUtility.assertStatus(response2, 400);
        AssertionUtility.assertContentType(response2, "application/json");
        AssertionUtility.assertJsonPathEquals(response2, "$.error", context.resolveObject(TestDataFactory.value("\"name is required\"")));
    }

    @Test(groups = {"smoke", "regression", "positive"}, enabled = true)
    public void createUpdateAndReadARecord_2ca879f5() {
        ScenarioContext context = new ScenarioContext();

        // 1. Log in with supplied test credentials
        RequestDefinition.Builder request1Builder = RequestDefinition.builder("POST", "/api/login");
        request1Builder.header("Content-Type", "application/json");
        request1Builder.contentType("application/json");
        request1Builder.body(TestDataFactory.json("{\"password\":\"${TEST_PASSWORD}\",\"username\":\"${TEST_USERNAME}\"}"));
        RequestDefinition request1 = request1Builder.build();
        AuthProvider auth1 = new NoAuthProvider();
        Response response1 = client.execute("Log in with supplied test credentials", request1, context, auth1);
        AssertionUtility.assertStatus(response1, 200);
        AssertionUtility.assertContentType(response1, "application/json");
        AssertionUtility.assertRequiredFields(response1, List.of("accessToken", "tokenType"));
        DynamicValueExtractor.extract(response1, "$.accessToken", context, "accessToken");

        // 2. Create a record
        RequestDefinition.Builder request2Builder = RequestDefinition.builder("POST", "/api/records");
        request2Builder.header("Content-Type", "application/json");
        request2Builder.contentType("application/json");
        request2Builder.body(TestDataFactory.json("{\"name\":\"Generated record\",\"quantity\":2}"));
        RequestDefinition request2 = request2Builder.build();
        AuthProvider auth2 = configuredAuth(context);
        Response response2 = client.execute("Create a record", request2, context, auth2);
        AssertionUtility.assertStatus(response2, 201);
        AssertionUtility.assertContentType(response2, "application/json");
        AssertionUtility.assertRequiredFields(response2, List.of("id", "name", "status"));
        DynamicValueExtractor.extract(response2, "$.id", context, "recordId");

        // 3. Update the created record
        RequestDefinition.Builder request3Builder = RequestDefinition.builder("PUT", "/api/records/${recordId}");
        request3Builder.header("Content-Type", "application/json");
        request3Builder.contentType("application/json");
        request3Builder.body(TestDataFactory.json("{\"name\":\"Updated by generated test\"}"));
        RequestDefinition request3 = request3Builder.build();
        AuthProvider auth3 = configuredAuth(context);
        Response response3 = client.execute("Update the created record", request3, context, auth3);
        AssertionUtility.assertStatus(response3, 200);
        AssertionUtility.assertContentType(response3, "application/json");
        AssertionUtility.assertRequiredFields(response3, List.of("id", "name", "status"));

        // 4. Retrieve final record state
        RequestDefinition.Builder request4Builder = RequestDefinition.builder("GET", "/api/records/${recordId}");
        request4Builder.contentType("application/json");
        RequestDefinition request4 = request4Builder.build();
        AuthProvider auth4 = configuredAuth(context);
        Response response4 = client.execute("Retrieve final record state", request4, context, auth4);
        AssertionUtility.assertStatus(response4, 200);
        AssertionUtility.assertContentType(response4, "application/json");
        AssertionUtility.assertRequiredFields(response4, List.of("id", "name", "status"));
        AssertionUtility.assertJsonPathEquals(response4, "$.name", context.resolveObject(TestDataFactory.value("\"Updated by generated test\"")));
        AssertionUtility.assertFormat(response4, "$.id", "uuid");
    }

    @Test(groups = {"regression", "negative"}, enabled = true)
    public void rejectAnUnauthenticatedListRequest_fdbbf5e6() {
        ScenarioContext context = new ScenarioContext();
        config.requireNegativeTestEnvironment();

        // 1. Log in with supplied test credentials
        RequestDefinition.Builder request1Builder = RequestDefinition.builder("POST", "/api/login");
        request1Builder.header("Content-Type", "application/json");
        request1Builder.contentType("application/json");
        request1Builder.body(TestDataFactory.json("{\"password\":\"${TEST_PASSWORD}\",\"username\":\"${TEST_USERNAME}\"}"));
        RequestDefinition request1 = request1Builder.build();
        AuthProvider auth1 = new NoAuthProvider();
        Response response1 = client.execute("Log in with supplied test credentials", request1, context, auth1);
        AssertionUtility.assertStatus(response1, 200);
        AssertionUtility.assertContentType(response1, "application/json");
        AssertionUtility.assertRequiredFields(response1, List.of("accessToken", "tokenType"));
        DynamicValueExtractor.extract(response1, "$.accessToken", context, "accessToken");

        // 2. List records without authentication
        RequestDefinition.Builder request2Builder = RequestDefinition.builder("GET", "/api/records");
        request2Builder.contentType("application/json");
        RequestDefinition request2 = request2Builder.build();
        AuthProvider auth2 = new NoAuthProvider();
        Response response2 = client.execute("List records without authentication", request2, context, auth2);
        AssertionUtility.assertStatus(response2, 401);
        AssertionUtility.assertContentType(response2, "application/json");
        AssertionUtility.assertFieldPresent(response2, "$.error");
    }

    @Test(groups = {"smoke", "regression", "positive", "asynchronous"}, enabled = true)
    public void processARecordAndObserveCompletion_1230e477() {
        ScenarioContext context = new ScenarioContext();

        // 1. Log in with supplied test credentials
        RequestDefinition.Builder request1Builder = RequestDefinition.builder("POST", "/api/login");
        request1Builder.header("Content-Type", "application/json");
        request1Builder.contentType("application/json");
        request1Builder.body(TestDataFactory.json("{\"password\":\"${TEST_PASSWORD}\",\"username\":\"${TEST_USERNAME}\"}"));
        RequestDefinition request1 = request1Builder.build();
        AuthProvider auth1 = new NoAuthProvider();
        Response response1 = client.execute("Log in with supplied test credentials", request1, context, auth1);
        AssertionUtility.assertStatus(response1, 200);
        AssertionUtility.assertContentType(response1, "application/json");
        AssertionUtility.assertRequiredFields(response1, List.of("accessToken", "tokenType"));
        DynamicValueExtractor.extract(response1, "$.accessToken", context, "accessToken");

        // 2. Create a record
        RequestDefinition.Builder request2Builder = RequestDefinition.builder("POST", "/api/records");
        request2Builder.header("Content-Type", "application/json");
        request2Builder.contentType("application/json");
        request2Builder.body(TestDataFactory.json("{\"name\":\"Generated record\",\"quantity\":2}"));
        RequestDefinition request2 = request2Builder.build();
        AuthProvider auth2 = configuredAuth(context);
        Response response2 = client.execute("Create a record", request2, context, auth2);
        AssertionUtility.assertStatus(response2, 201);
        AssertionUtility.assertContentType(response2, "application/json");
        AssertionUtility.assertRequiredFields(response2, List.of("id", "name", "status"));
        DynamicValueExtractor.extract(response2, "$.id", context, "recordId");

        // 3. Start asynchronous processing
        RequestDefinition.Builder request3Builder = RequestDefinition.builder("POST", "/api/records/${recordId}/process");
        request3Builder.header("Content-Type", "application/json");
        request3Builder.contentType("application/json");
        request3Builder.body(TestDataFactory.json("{}"));
        RequestDefinition request3 = request3Builder.build();
        AuthProvider auth3 = configuredAuth(context);
        Response response3 = client.execute("Start asynchronous processing", request3, context, auth3);
        AssertionUtility.assertStatus(response3, 202);
        AssertionUtility.assertContentType(response3, "application/json");
        AssertionUtility.assertRequiredFields(response3, List.of("jobId", "status"));
        DynamicValueExtractor.extract(response3, "$.jobId", context, "jobId");

        // 4. Poll the processing job
        RequestDefinition.Builder request4Builder = RequestDefinition.builder("GET", "/api/jobs/${jobId}");
        request4Builder.contentType("application/json");
        RequestDefinition request4 = request4Builder.build();
        AuthProvider auth4 = configuredAuth(context);
        Response response4 = PollingUtility.poll("Poll the processing job",
                () -> client.execute("Poll the processing job", request4, context, auth4),
                candidate -> Objects.equals(candidate.jsonPath().get("status"), context.resolveObject(TestDataFactory.value("\"completed\""))),
                Duration.ofSeconds(config.pollTimeoutSeconds()),
                Duration.ofMillis(config.pollIntervalMillis()));
        AssertionUtility.assertStatus(response4, 200);
        AssertionUtility.assertContentType(response4, "application/json");
        AssertionUtility.assertRequiredFields(response4, List.of("jobId", "status"));
        AssertionUtility.assertJsonPathEquals(response4, "$.status", context.resolveObject(TestDataFactory.value("\"completed\"")));

        // 5. Verify processed record state
        RequestDefinition.Builder request5Builder = RequestDefinition.builder("GET", "/api/records/${recordId}");
        request5Builder.contentType("application/json");
        RequestDefinition request5 = request5Builder.build();
        AuthProvider auth5 = configuredAuth(context);
        Response response5 = client.execute("Verify processed record state", request5, context, auth5);
        AssertionUtility.assertStatus(response5, 200);
        AssertionUtility.assertContentType(response5, "application/json");
        AssertionUtility.assertRequiredFields(response5, List.of("id", "name", "status"));
        AssertionUtility.assertJsonPathEquals(response5, "$.status", context.resolveObject(TestDataFactory.value("\"processed\"")));
    }
}
