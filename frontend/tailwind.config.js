/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        navy: { 950: "#06142A", 900: "#0B1F3A", 800: "#122B4D", 700: "#1B3A63", 600: "#28507F" },
        brand: { 50: "#F0FDFA", 100: "#CCFBF1", 200: "#99F6E4", 500: "#14B8A6", 600: "#0D9488", 700: "#0F766E", 800: "#115E59", 900: "#134E4A" },
        ink: { DEFAULT: "#0F172A", muted: "#475569", subtle: "#64748B" },
        line: "#E2E8F0",
        canvas: "#F8FAFC",
        ok: { DEFAULT: "#15803D", bg: "#F0FDF4" },
        warn: { DEFAULT: "#B45309", bg: "#FFFBEB" },
        bad: { DEFAULT: "#B91C1C", bg: "#FEF2F2" },
        info: { DEFAULT: "#1D4ED8", bg: "#EFF6FF" },
      },
      fontFamily: {
        sans: ["Inter", "ui-sans-serif", "system-ui", "-apple-system", "Segoe UI", "Roboto", "sans-serif"],
        mono: ["JetBrains Mono", "ui-monospace", "SFMono-Regular", "Menlo", "monospace"],
      },
      borderRadius: { DEFAULT: "6px", md: "8px", lg: "10px" },
      boxShadow: { card: "0 1px 2px rgba(15, 23, 42, 0.04)", pop: "0 12px 32px rgba(15, 23, 42, 0.14)" },
      maxWidth: { prose: "72ch" },
    },
  },
  plugins: [],
};
