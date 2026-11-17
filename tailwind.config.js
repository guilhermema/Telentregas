/** @type {import('tailwindcss').Config} */
module.exports = {
  content: ["./app/templates/**/*.html", "./app/static/**/*.js"],
  theme: {
    extend: {
      colors: {
        brand: {
          50: "#eef2ff",
          100: "#e0e7ff",
          200: "#c7d2fe",
          300: "#a5b4fc",
          400: "#818cf8",
          500: "#6366f1",
          600: "#4f46e5",
          700: "#4338ca",
          800: "#3730a3",
          900: "#312e81",
        },
      },
      fontFamily: {
        sans: ["Inter", "ui-sans-serif", "system-ui", "sans-serif"],
      },
      borderRadius: {
        DEFAULT: "0.5rem",
        lg: "0.5rem",
        xl: "0.75rem",
      },
      boxShadow: {
        card: "0 1px 2px 0 rgb(15 23 42 / 0.05)",
        "card-lg": "0 1px 3px 0 rgb(15 23 42 / 0.08)",
      },
    },
  },
  plugins: [],
};
