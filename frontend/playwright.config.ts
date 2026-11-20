import { defineConfig } from "@playwright/test";
export default defineConfig({
  testDir: "./e2e",
  workers: 1,
  use: { baseURL: "http://127.0.0.1:8001", headless: true },
  reporter: "list",
  webServer: {
    command:
      "conda run --no-capture-output -n labagent python -m scripts.serve_demo",
    cwd: "..",
    url: "http://127.0.0.1:8001/api/health",
    reuseExistingServer: true,
    timeout: 60000,
  },
});
