import type { Config } from "tailwindcss";

// Apple design language (PRD §4.1): system typography, Apple palette,
// hairline dividers over boxes, one accent colour.
const config: Config = {
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        ink: "#1D1D1F",        // near-black text
        canvas: "#F5F5F7",     // Apple light grey background
        accent: "#0071E3",     // system blue
        hairline: "#D2D2D7",   // dividers — instead of boxes
        subtle: "#86868B",     // secondary text
        good: "#34C759",       // score: strong match
        warn: "#FF9F0A",       // score: partial
        bad: "#FF3B30",        // score: weak
      },
      fontFamily: {
        sans: [
          "-apple-system", "BlinkMacSystemFont", "SF Pro Text",
          "Segoe UI", "Helvetica Neue", "Arial", "sans-serif",
        ],
      },
      borderRadius: {
        apple: "18px",
      },
    },
  },
  plugins: [],
};
export default config;
