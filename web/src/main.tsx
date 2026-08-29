import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { ConfigProvider, App as AntApp } from "antd";
import zhCN from "antd/locale/zh_CN";
import App from "./App";
import { RoleProvider } from "./rbac";
import { AppContextProvider } from "./appContext";
import "./styles.css";

const queryClient = new QueryClient({
  defaultOptions: {
    queries: { staleTime: 30_000, retry: 1, refetchOnWindowFocus: false }
  }
});

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <ConfigProvider
      locale={zhCN}
      theme={{
        token: {
          colorPrimary: "#116da8",
          colorInfo: "#116da8",
          colorSuccess: "#159a8c",
          colorWarning: "#e29a32",
          colorError: "#d65059",
          colorText: "#102f48",
          colorTextSecondary: "#6b8193",
          colorBorder: "#d9e4ec",
          colorBgLayout: "#eef3f7",
          colorBgContainer: "#ffffff",
          borderRadius: 12,
          borderRadiusLG: 18,
          controlHeight: 38,
          fontFamily: '"Inter","PingFang SC","Microsoft YaHei",sans-serif'
        },
        components: {
          Card: {
            headerBg: "transparent",
            headerFontSize: 16,
            headerFontSizeSM: 14
          },
          Button: { borderRadius: 9 },
          Input: { activeBorderColor: "#116da8", hoverBorderColor: "#6caed0" },
          Select: { optionSelectedBg: "#e9f4f7" },
          Table: { headerBg: "#f4f8fa", headerColor: "#49657a", rowHoverBg: "#f7fbfc" },
          Timeline: { tailColor: "#c9dbe4" }
        }
      }}
    >
      <AntApp>
        <QueryClientProvider client={queryClient}>
          <BrowserRouter>
            <RoleProvider>
              <AppContextProvider>
                <App />
              </AppContextProvider>
            </RoleProvider>
          </BrowserRouter>
        </QueryClientProvider>
      </AntApp>
    </ConfigProvider>
  </React.StrictMode>
);
