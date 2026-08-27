/** @type {import('tailwindcss').Config} */
export default {
  darkMode: ['class'],
  content: ['./index.html', './src/**/*.{js,ts,jsx,tsx}'],
  theme: {
    extend: {
      colors: {
        border: 'hsl(var(--border))',
        input: 'hsl(var(--input))',
        ring: 'hsl(var(--ring))',
        background: 'hsl(var(--background))',
        foreground: 'hsl(var(--foreground))',
        primary: {
          DEFAULT: 'hsl(var(--primary))',
          foreground: 'hsl(var(--primary-foreground))',
        },
        secondary: {
          DEFAULT: 'hsl(var(--secondary))',
          foreground: 'hsl(var(--secondary-foreground))',
        },
        destructive: {
          DEFAULT: 'hsl(var(--destructive))',
          foreground: 'hsl(var(--destructive-foreground))',
        },
        muted: {
          DEFAULT: 'hsl(var(--muted))',
          foreground: 'hsl(var(--muted-foreground))',
        },
        accent: {
          DEFAULT: 'hsl(var(--accent))',
          foreground: 'hsl(var(--accent-foreground))',
        },
        popover: {
          DEFAULT: 'hsl(var(--popover))',
          foreground: 'hsl(var(--popover-foreground))',
        },
        card: {
          DEFAULT: 'hsl(var(--card))',
          foreground: 'hsl(var(--card-foreground))',
        },
        // GitHub Primer Palette
        gh: {
          canvas: {
            DEFAULT: '#ffffff',
            subtle: '#f6f8fa',
            inset: '#f6f8fa',
            dark: '#0d1117',
            'dark-subtle': '#161b22',
            'dark-overlay': '#21262d',
            'dark-inset': '#010409',
          },
          border: {
            DEFAULT: '#d0d7de',
            muted: '#d8dee4',
            dark: '#30363d',
            'dark-muted': '#21262d',
          },
          fg: {
            DEFAULT: '#1f2328',
            muted: '#656d76',
            subtle: '#8c959f',
            dark: '#e6edf3',
            'dark-muted': '#848d97',
            'dark-subtle': '#6e7681',
          },
          blue: {
            DEFAULT: '#0969da',
            emphasis: '#0969da',
            dark: '#2f81f7',
            'dark-emphasis': '#1f6feb',
          },
          green: {
            DEFAULT: '#1a7f37',
            emphasis: '#1f883d',
            dark: '#3fb950',
            'dark-emphasis': '#238636',
          },
          amber: {
            DEFAULT: '#9a6700',
            emphasis: '#bf8700',
            dark: '#d29922',
            'dark-emphasis': '#9e6a03',
          },
          red: {
            DEFAULT: '#cf222e',
            emphasis: '#d1242f',
            dark: '#f85149',
            'dark-emphasis': '#da3633',
          },
          purple: {
            DEFAULT: '#8250df',
            emphasis: '#8250df',
            dark: '#a371f7',
            'dark-emphasis': '#8957e5',
          },
        },
        // Security Levels
        sec: {
          public: '#1a7f37',
          internal: '#0969da',
          confidential: '#9a6700',
          restricted: '#cf222e',
        },
      },
      borderRadius: {
        lg: '6px',
        md: '6px',
        sm: '4px',
      },
    },
  },
  plugins: [],
};
