import { StrictMode } from "react"
import { createRoot } from "react-dom/client"

import { App, AppBoundary } from "./App.jsx"
import "./styles.css"

createRoot(document.getElementById("root")).render(
  <StrictMode>
    <AppBoundary>
      <App />
    </AppBoundary>
  </StrictMode>,
)
