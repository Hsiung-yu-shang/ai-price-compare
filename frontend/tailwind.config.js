/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{vue,js,ts,jsx,tsx}",
  ],
  darkMode: 'class',
  theme: {
    extend: {
      colors: {
        brand: {
          openai: '#10a37f',
          anthropic: '#d97706',
          google: '#4285f4',
        }
      }
    },
  },
  plugins: [],
}
