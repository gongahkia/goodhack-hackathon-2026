import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}", "./lib/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        ink: "#17201c",
        moss: "#405b48",
        mint: "#d9f2e2",
        sun: "#f4c95d",
        clay: "#b6654b"
      },
      boxShadow: {
        app: "0 20px 60px rgba(23, 32, 28, 0.16)"
      }
    }
  },
  plugins: []
};

export default config;
