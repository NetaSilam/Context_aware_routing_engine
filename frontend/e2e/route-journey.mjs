import { chromium } from "playwright";

const baseUrl = process.env.E2E_BASE_URL ?? "http://frontend:8080";
const email = `e2e-${Date.now()}@example.com`;

const browser = await chromium.launch({
  headless: true,
  args: ["--unsafely-treat-insecure-origin-as-secure=http://frontend:8080"],
});
const page = await browser.newPage();

try {
  await page.goto(baseUrl, { waitUntil: "domcontentloaded" });
  await page.getByRole("button", { name: "Need an account? Sign up" }).click();
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password", { exact: true }).fill("correct-password");
  await page.getByRole("button", { name: "Create account" }).click();
  await page.locator(".session-card").getByText(`Signed in as ${email}`, { exact: true }).waitFor();

  await page.getByRole("button", { name: "Edit route preferences" }).click();
  await page.getByLabel("Vehicle type").selectOption("motorcycle");
  await page.getByRole("button", { name: "Save preferences" }).click();
  await page.getByText(/motorcycle/i).waitFor();

  await page.getByRole("region", { name: "origin address search" }).getByLabel("Address").fill("Tel Aviv");
  await page.getByRole("button", { name: "Search origin" }).click();
  await page.getByText("Tel Aviv Center").click();
  await page.getByRole("region", { name: "destination address search" }).getByLabel("Address").fill("Tel Aviv");
  await page.getByRole("button", { name: "Search destination" }).click();
  await page.getByText("Tel Aviv Center").click();
  await page.getByLabel("Destination longitude").fill("34.7900");
  await page.getByLabel("Destination latitude").fill("32.0800");
  await page.getByRole("button", { name: "Compare routes" }).click();
  await page.getByRole("heading", { name: "Route job completed" }).waitFor({ timeout: 20_000 });
  await page.getByLabel("Route result map").waitFor();
  await page.getByText("Route history").waitFor();

  const savedUrl = page.url();
  if (!savedUrl.includes("routeJob=")) throw new Error("completed job was not written to the URL");
  await page.reload({ waitUntil: "domcontentloaded" });
  await page.getByRole("heading", { name: "Route job completed" }).waitFor({ timeout: 10_000 });

  await page.getByRole("button", { name: "Open saved result" }).click();
  await page.getByRole("heading", { name: "Route job completed" }).waitFor();
  await page.getByRole("button", { name: "Run again" }).click();
  await page.getByRole("heading", { name: "Route job completed" }).waitFor({ timeout: 20_000 });

  page.on("dialog", (dialog) => dialog.accept());
  await page.getByRole("button", { name: "Delete" }).first().click();
  await page.getByRole("button", { name: "Clear history" }).click();
  await page.getByText("No completed routes yet.").waitFor();
  await page.getByRole("button", { name: "Sign out" }).click();
  await page.getByRole("heading", { name: /Route recommendations are personalized/ }).waitFor();
} finally {
  await browser.close();
}
