module.exports = {
  content: ["./app/**/*.{js,jsx}", "./components/**/*.{js,jsx}"],
  theme: {
    extend: {
      colors: {
        mira: {
          black: "#000000",
          dark: "#050816",
          slate: "#0f172a",
          panel: "#111827",
          blue: "#2563eb",
          "blue-bright": "#3b82f6",
          "blue-light": "#60a5fa",
          "blue-dark": "#1e3a8a",
          white: "#ffffff",
          gray: "#94a3b8",
        },
      },
      fontFamily: { display: ["var(--font-display)", "sans-serif"], body: ["var(--font-body)", "sans-serif"] },
    },
  },
  plugins: [],
};
