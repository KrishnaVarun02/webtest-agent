package generated.listeners;

import com.aventstack.extentreports.ExtentReports;
import com.aventstack.extentreports.ExtentTest;
import com.aventstack.extentreports.reporter.ExtentSparkReporter;
import framework.ExecutionTrace;
import framework.SecretRedactor;
import java.io.PrintWriter;
import java.io.StringWriter;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;
import org.testng.ISuite;
import org.testng.ISuiteListener;
import org.testng.ITestListener;
import org.testng.ITestResult;

/** Extent/TestNG listener. Every value crosses SecretRedactor before reaching HTML. */
public final class WebTestReportListener implements ITestListener, ISuiteListener {
    private static final Map<ITestResult, ExtentTest> TESTS = new ConcurrentHashMap<>();
    private static ExtentReports reports;

    private static synchronized ExtentReports reports() {
        if (reports == null) {
            try {
                Path directory = Path.of("target", "webtest-report");
                Files.createDirectories(directory);
                ExtentSparkReporter reporter = new ExtentSparkReporter(directory.resolve("index.html").toString());
                reporter.config().setDocumentTitle("WebTest Agent execution report");
                reporter.config().setReportName("Authorized API scenarios");
                reports = new ExtentReports();
                reports.attachReporter(reporter);
                reports.setSystemInfo("environment", SecretRedactor.redactText(
                        System.getenv().getOrDefault("WEBTEST_ENVIRONMENT", "unspecified")));
            } catch (Exception exception) {
                throw new IllegalStateException("unable to initialize sanitized HTML report", exception);
            }
        }
        return reports;
    }

    @Override public void onTestStart(ITestResult result) {
        ExecutionTrace.start();
        TESTS.put(result, reports().createTest(result.getTestClass().getName() + "." + result.getMethod().getMethodName()));
    }

    @Override public void onTestSuccess(ITestResult result) { finish(result, "PASS", null); }
    @Override public void onTestFailure(ITestResult result) { finish(result, "FAIL", result.getThrowable()); }
    @Override public void onTestSkipped(ITestResult result) { finish(result, "SKIP", result.getThrowable()); }

    private static void finish(ITestResult result, String outcome, Throwable failure) {
        ExtentTest test = TESTS.remove(result);
        if (test == null) test = reports().createTest(result.getMethod().getMethodName());
        for (ExecutionTrace.Event event : ExecutionTrace.drain()) {
            test.info(SecretRedactor.redactText(event.kind() + "\n" + event.detail()));
        }
        test.info("elapsedMs=" + Math.max(0L, result.getEndMillis() - result.getStartMillis()));
        if (outcome.equals("PASS")) test.pass("passed");
        else if (outcome.equals("SKIP")) test.skip(failure == null ? "skipped" : stack(failure));
        else test.fail(failure == null ? "failed" : stack(failure));
    }

    private static String stack(Throwable throwable) {
        StringWriter output = new StringWriter();
        throwable.printStackTrace(new PrintWriter(output));
        return SecretRedactor.redactText(output.toString());
    }

    @Override public synchronized void onFinish(ISuite suite) {
        if (reports != null) reports.flush();
    }
}
