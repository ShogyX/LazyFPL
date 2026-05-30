/** @type {import('tailwindcss').Config} */
// "Data-Dense Dashboard" system (ui-ux-pro-max): blue data + amber highlights,
// WCAG-AA. Colors are CSS variables (see src/index.css) so a dark mode can swap
// them without touching markup.
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        primary: "var(--color-primary)",
        "on-primary": "var(--color-on-primary)",
        secondary: "var(--color-secondary)",
        accent: "var(--color-accent)",
        bg: "var(--color-background)",
        surface: "var(--color-surface)",
        fg: "var(--color-foreground)",
        muted: "var(--color-muted)",
        "muted-fg": "var(--color-muted-foreground)",
        border: "var(--color-border)",
        positive: "var(--color-positive)",
        destructive: "var(--color-destructive)",
        ring: "var(--color-ring)",
      },
      fontFamily: {
        sans: ["Fira Sans", "ui-sans-serif", "system-ui", "sans-serif"],
        mono: ["Fira Code", "ui-monospace", "monospace"],
      },
      borderRadius: { card: "10px" },
      transitionDuration: { DEFAULT: "180ms" },
    },
  },
  plugins: [],
};
