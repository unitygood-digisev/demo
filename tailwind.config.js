/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        unity: {
          cyan: '#13c1db',    // 活力青藍
          green: '#81cf9f',   // 永續淺綠
          yellow: '#fdde59',  // 溫暖亮黃
        }
      },
      animation: {
        shake: 'shake 0.3s cubic-bezier(.36,.07,.19,.97) both',
      },
      keyframes: {
        shake: {
          '10%, 90%': { transform: 'translate3d(-1px, 0, 0)' },
          '20%, 80%': { transform: 'translate3d(2px, 0, 0)' },
          '30%, 50%, 70%': { transform: 'translate3d(-2px, 0, 0)' },
          '40%, 60%': { transform: 'translate3d(2px, 0, 0)' }
        }
      }
    },
  },
  plugins: [],
}