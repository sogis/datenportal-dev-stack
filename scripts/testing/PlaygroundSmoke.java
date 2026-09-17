import com.microsoft.playwright.*;
import com.microsoft.playwright.options.AriaRole;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.List;

/** Browser half of the isolated GRETL -> S3 -> portal publication test. */
class PlaygroundSmoke {
    public static void main(String[] args) {
        try (var playwright = Playwright.create();
             var browser = playwright.chromium().launch(new BrowserType.LaunchOptions().setHeadless(true));
             var context = browser.newContext(new Browser.NewContextOptions().setViewportSize(1440, 1000))) {
            // Public test URLs are Docker aliases; map only this isolated fixture gateway for the host browser.
            context.route("http://proxy:8000/**", route -> route.resume(new Route.ResumeOptions()
                    .setUrl(route.request().url().replace("http://proxy:8000", args[1]))));
            var page = context.newPage();
            page.setDefaultTimeout(60000);
            List<String> errors = new ArrayList<>();
            page.onPageError(errors::add);
            page.onConsoleMessage(message -> { if (message.type().equals("error")) System.err.println(message.text()); });
            page.onRequestFailed(request -> System.err.println(request.method()+" "+request.url()+": "+request.failure()));
            try {
                page.navigate(args[0]);
                page.waitForSelector(".dp-schema-explorer__node--schema:has-text('opendata')");
                page.waitForFunction("() => !document.querySelector('.dp-explore-runtime-overlay')");
                var expand = page.getByRole(AriaRole.BUTTON, new Page.GetByRoleOptions().setName("opendata ausklappen"));
                if (expand.count() > 0) expand.click();
                int count = page.locator(".dp-schema-explorer__node--table").count();
                if (count != Integer.parseInt(args[2])) throw new AssertionError("Expected " + args[2] + " views, got " + count);
                page.getByRole(AriaRole.BUTTON, new Page.GetByRoleOptions().setName("Ausführen").setExact(true)).click();
                page.waitForSelector("[aria-label='SQL Ergebnis']");
                if (!errors.isEmpty()) throw new AssertionError(errors);
                page.screenshot(new Page.ScreenshotOptions().setPath(Path.of(args[3])).setFullPage(true));
                System.out.println("PASS: GRETL catalog attached in DuckDB-Wasm, " + count + " views, Parquet query succeeded.");
            } catch (RuntimeException | AssertionError error) {
                System.err.println("Browser errors: " + errors);
                System.err.println(page.locator("body").innerText());
                throw error;
            }
        }
    }
}
