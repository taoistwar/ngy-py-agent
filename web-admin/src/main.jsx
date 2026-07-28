import { StrictMode } from "react"
import { createRoot } from "react-dom/client"
import { loader } from "@monaco-editor/react"
import App from "./App"
import "./index.css"

loader.config({
  paths: {
    vs: `${import.meta.env.BASE_URL}monaco-editor/min/vs`,
  },
})

createRoot(document.getElementById("root")).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
