import type { Config } from "tailwindcss";

/**
 * The theme is a *mapping*, not a copy. Every value below points at a custom
 * property declared in `styles/tokens.css`, which is the resolved form of D5.
 * There is deliberately not a single hex literal in this file — if a token
 * changes, it changes in one place.
 */
const config: Config = {
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}", "./lib/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        accent: {
          DEFAULT: "var(--rd-accent)",
          deep: "var(--rd-accent-deep)",
          soft: "var(--rd-accent-soft)",
        },
        "on-accent": "var(--rd-on-accent)",
        surface: {
          DEFAULT: "var(--rd-surface)",
          soft: "var(--rd-surface-soft)",
          raised: "var(--rd-surface-raised)",
          inset: "var(--rd-surface-inset)",
        },
        hairline: {
          DEFAULT: "var(--rd-hairline)",
          strong: "var(--rd-hairline-strong)",
          faint: "var(--rd-hairline-faint)",
        },
        ink: {
          DEFAULT: "var(--rd-text)",
          secondary: "var(--rd-text-secondary)",
          mute: "var(--rd-text-mute)",
          faint: "var(--rd-text-faint)",
        },
        status: {
          live: "var(--rd-status-live)",
          building: "var(--rd-status-building)",
          failed: "var(--rd-status-failed)",
          draining: "var(--rd-status-draining)",
          unknown: "var(--rd-status-unknown)",
        },
      },
      borderRadius: {
        xs: "var(--rd-radius-xs)",
        sm: "var(--rd-radius-sm)",
        md: "var(--rd-radius-md)",
        lg: "var(--rd-radius-lg)",
        xl: "var(--rd-radius-xl)",
        full: "var(--rd-radius-full)",
      },
      spacing: {
        xxs: "var(--rd-space-xxs)",
        xs: "var(--rd-space-xs)",
        sm: "var(--rd-space-sm)",
        md: "var(--rd-space-md)",
        lg: "var(--rd-space-lg)",
        xl: "var(--rd-space-xl)",
        xxl: "var(--rd-space-xxl)",
        huge: "var(--rd-space-huge)",
      },
      fontFamily: {
        sans: ["var(--rd-font-sans)"],
        mono: ["var(--rd-font-mono)"],
      },
      fontSize: {
        "display-lg": ["var(--rd-text-display-lg)", { lineHeight: "1.15", letterSpacing: "-0.72px" }],
        "display-md": ["var(--rd-text-display-md)", { lineHeight: "1.2", letterSpacing: "-0.42px" }],
        "heading-lg": ["var(--rd-text-heading-lg)", { lineHeight: "1.2" }],
        "heading-md": ["var(--rd-text-heading-md)", { lineHeight: "1.4" }],
        body: ["var(--rd-text-body)", { lineHeight: "1.5" }],
        button: ["var(--rd-text-button)", { lineHeight: "1" }],
        code: ["var(--rd-text-code)", { lineHeight: "1.5" }],
        caption: ["var(--rd-text-caption)", { lineHeight: "1.45" }],
        micro: ["var(--rd-text-micro)", { lineHeight: "1.45" }],
      },
      boxShadow: {
        "elev-1": "var(--rd-elev-1)",
        "elev-2": "var(--rd-elev-2)",
        "elev-3": "var(--rd-elev-3)",
      },
    },
  },
  plugins: [],
};

export default config;
