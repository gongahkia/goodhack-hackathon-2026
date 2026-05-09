import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}", "./lib/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        ink: "rgb(var(--color-ink) / <alpha-value>)",
        moss: "rgb(var(--color-moss) / <alpha-value>)",
        mint: "rgb(var(--color-mint) / <alpha-value>)",
        sun: "rgb(var(--color-sun) / <alpha-value>)",
        clay: "rgb(var(--color-clay) / <alpha-value>)"
      },
      boxShadow: {
        app: "0 20px 60px rgba(23, 32, 28, 0.16)"
      }
    }
  },
  plugins: []
};

export default config;
