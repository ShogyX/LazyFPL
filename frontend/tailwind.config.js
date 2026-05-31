/** @type {import('tailwindcss').Config} */
// "Broadcast" design system — tokens are CSS variables (see src/index.css) so
// dark/light + accent hue swap without touching markup. Tailwind utilities map
// onto the same vars for the spots that use them.
export default {
  darkMode: ['selector', '[data-theme="dark"]'],
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        accent: "var(--accent)",
        "accent-ink": "var(--accent-ink)",
        bg: "var(--ink-0)",
        surface: "var(--surface)",
        "surface-2": "var(--surface-2)",
        "surface-3": "var(--surface-3)",
        fg: "var(--fg)",
        "fg-dim": "var(--fg-dim)",
        "fg-faint": "var(--fg-faint)",
        line: "var(--line)",
        "line-2": "var(--line-2)",
        bad: "var(--bad)",
        warn: "var(--warn)",
      },
      fontFamily: {
        sans: ["Archivo", "ui-sans-serif", "system-ui", "sans-serif"],
        mono: ["JetBrains Mono", "ui-monospace", "monospace"],
      },
      borderRadius: { card: "var(--radius)" },
    },
  },
  plugins: [],
};
