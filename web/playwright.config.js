var __assign = (this && this.__assign) || function () {
    __assign = Object.assign || function(t) {
        for (var s, i = 1, n = arguments.length; i < n; i++) {
            s = arguments[i];
            for (var p in s) if (Object.prototype.hasOwnProperty.call(s, p))
                t[p] = s[p];
        }
        return t;
    };
    return __assign.apply(this, arguments);
};
import { defineConfig, devices } from "@playwright/test";
var nodePath = "C:/Users/25301/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node.exe";
export default defineConfig({
    testDir: "./e2e",
    timeout: 90000,
    expect: { timeout: 30000 },
    fullyParallel: false,
    workers: 1,
    reporter: [["list"], ["json", { outputFile: "../data/web_e2e_report.json" }]],
    use: {
        baseURL: "http://127.0.0.1:5173",
        channel: "chrome",
        trace: "retain-on-failure"
    },
    webServer: [
        {
            command: "python -B -m uvicorn api.main:app --host 127.0.0.1 --port 8000",
            cwd: "..",
            url: "http://127.0.0.1:8000/api/v1/health",
            reuseExistingServer: true,
            timeout: 120000
        },
        {
            command: "\"".concat(nodePath, "\" ./node_modules/vite/bin/vite.js --host 127.0.0.1 --port 5173"),
            cwd: ".",
            url: "http://127.0.0.1:5173",
            reuseExistingServer: true,
            timeout: 120000
        }
    ],
    projects: [
        { name: "desktop-1440", use: __assign(__assign({}, devices["Desktop Chrome"]), { viewport: { width: 1440, height: 900 } }) },
        { name: "tablet-768", use: __assign(__assign({}, devices["Desktop Chrome"]), { viewport: { width: 768, height: 1024 } }) },
        { name: "mobile-375", use: __assign(__assign({}, devices["Desktop Chrome"]), { viewport: { width: 375, height: 812 }, isMobile: true, hasTouch: true }) }
    ]
});
