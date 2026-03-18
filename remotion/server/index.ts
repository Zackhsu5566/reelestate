import express from "express";
import { handleRender, handleStatus, handleHealth } from "./render-handler";

const app = express();
const PORT = process.env.PORT || 3100;
const API_TOKEN = process.env.RENDER_API_TOKEN;

app.use(express.json({ limit: "1mb" }));

// Auth middleware (skip for health check)
app.use((req, res, next) => {
  if (req.path === "/health") return next();
  if (!API_TOKEN) return next(); // no token configured = open access (dev mode)
  const token = req.headers.authorization?.replace("Bearer ", "");
  if (token !== API_TOKEN) {
    res.status(401).json({ error: "Unauthorized" });
    return;
  }
  next();
});

app.get("/health", handleHealth);
app.post("/render", handleRender);
app.get("/render/:jobId", handleStatus);
app.listen(PORT, () => {
  console.log(
    JSON.stringify({
      ts: new Date().toISOString(),
      module: "server",
      msg: `Render server listening on :${PORT}`,
    }),
  );
});
