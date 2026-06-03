/** @type {import('tailwindcss').Config} */
module.exports = {
  content: [
    './public/**/*.html',
    './src/**/*.js',
  ],
  theme: {
    extend: {
      colors: {
        glow: {
          main:    '#0b0f19',
          card:    '#131a26',
          primary: '#6366f1',
          accent:  '#f59e0b',
          text:    '#e2e8f0',
        },
      },
      animation: {
        // 規格書指定的 cubic-bezier
        'pulse-slow': 'pulse 3s cubic-bezier(0.4, 0, 0.6, 1) infinite',
      },
    },
  },
  plugins: [],
};
