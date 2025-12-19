/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,ts,jsx,tsx}'],
  theme: {
    extend: {
      colors: {
        // Node status colors
        draft: '#fbbf24',     // Yellow
        approved: '#22c55e',  // Green
        synced: '#3b82f6',    // Blue
        partial: '#f97316',   // Orange
        conflict: '#ef4444',  // Red
      },
    },
  },
  plugins: [],
};
