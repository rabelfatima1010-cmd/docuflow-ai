import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Static site (frontend/out) served by the FastAPI backend, so the whole app is one service.
  output: "export",
  trailingSlash: true,
  devIndicators: false,
};

export default nextConfig;
