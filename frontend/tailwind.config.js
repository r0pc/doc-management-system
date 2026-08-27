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
        // Primer Tokens
        primer: {
          canvas: {
            default: '#ffffff',
            subtle: '#f6f8fa',
            inset: '#f6f8fa',
            'default-dark': '#0d1117',
            'subtle-dark': '#161b22',
            'overlay-dark': '#21262d',
            'inset-dark': '#010409',
          },
          border: {
            default: '#d0d7de',
            muted: '#d8dee4',
            'default-dark': '#30363d',
            'muted-dark': '#21262d',
          },
          fg: {
            default: '#1f2328',
            muted: '#656d76',
            subtle: '#8c959f',
            'default-dark': '#e6edf3',
            'muted-dark': '#848d97',
            'subtle-dark': '#6e7681',
          },
          blue: {
            default: '#0969da',
            emphasis: '#0969da',
            'default-dark': '#2f81f7',
            'emphasis-dark': '#1f6feb',
          },
          green: {
            default: '#1a7f37',
            emphasis: '#1f883d',
            'default-dark': '#3fb950',
            'emphasis-dark': '#238636',
          },
          amber: {
            default: '#9a6700',
            emphasis: '#bf8700',
            'default-dark': '#d29922',
            'emphasis-dark': '#9e6a03',
          },
          red: {
            default: '#cf222e',
            emphasis: '#d1242f',
            'default-dark': '#f85149',
            'emphasis-dark': '#da3633',
          },
          purple: {
            default: '#8250df',
            emphasis: '#8250df',
            'default-dark': '#a371f7',
            'emphasis-dark': '#8957e5',
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
