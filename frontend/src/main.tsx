import React from "react";
import ReactDOM from "react-dom/client";
import "bootstrap/dist/css/bootstrap.min.css";
import "./styles.css";
import { AuthGate } from "./AuthGate";

// Bootstrapのカラーモードを、OSのライト/ダーク設定に追従させる
const mq = window.matchMedia("(prefers-color-scheme: dark)");
const applyTheme = () =>
  document.documentElement.setAttribute("data-bs-theme", mq.matches ? "dark" : "light");
applyTheme();
mq.addEventListener("change", applyTheme);

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <AuthGate />
  </React.StrictMode>,
);
