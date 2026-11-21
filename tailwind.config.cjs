module.exports = {
  content: ['./templates/**/*.html', './static/js/**/*.js'],
  theme: {
    extend: {
      fontFamily: {
        sans: ['Open Sans', 'system-ui', 'sans-serif'],
        display: ['Poppins', 'Arial', 'sans-serif'],
        mono: ['ui-monospace', 'SFMono-Regular', 'Consolas', 'monospace'],
      },
      colors: {
        orange: { 50: '#fff5f0', 100: '#fff3e6', 200: '#ffe1c4', 300: '#ffb584', 400: '#ff8c42', 500: '#f15600', 600: '#d64d00', 700: '#b84000', 800: '#943700', 900: '#783000' },
        slate: { 50: '#f8f9fa', 100: '#f1f3f5', 200: '#e9ecef', 300: '#ced4da', 400: '#9298a0', 500: '#6c757d', 600: '#565e67', 700: '#3e4350', 800: '#2a2a48', 900: '#1b1b2f', 950: '#141422' },
      },
    },
  },
  plugins: [],
};
