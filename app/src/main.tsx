import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import "@fontsource/archivo-black";
import "@fontsource/work-sans/400.css";
import "@fontsource/work-sans/600.css";
import "@fontsource/space-mono";
import "./styles/rawblock.css";
import App from "./App";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
