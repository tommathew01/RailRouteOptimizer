import type { MetadataRoute } from "next";

export default function manifest(): MetadataRoute.Manifest {
  return {
    name: "RailRoute Optimizer",
    short_name: "RailRoute",
    description: "Find same-train segment combinations when a direct ticket is unavailable.",
    start_url: "/",
    display: "standalone",
    background_color: "#f6f8f9",
    theme_color: "#0f4c5c",
    icons: [
      { src: "/icon.svg", sizes: "any", type: "image/svg+xml", purpose: "any" },
      { src: "/icon-maskable.svg", sizes: "any", type: "image/svg+xml", purpose: "maskable" },
    ],
  };
}
