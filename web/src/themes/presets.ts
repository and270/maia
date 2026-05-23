import type { DashboardTheme, ThemeTypography, ThemeLayout } from "./types";

/**
 * Built-in dashboard themes.
 *
 * Each theme defines its own palette, typography, and layout so switching
 * themes produces visible changes beyond just color — fonts, density, and
 * corner-radius all shift to match the theme's personality.
 *
 * Theme names must stay in sync with the backend's
 * `_BUILTIN_DASHBOARD_THEMES` list in `hermes_cli/web_server.py`.
 */

// ---------------------------------------------------------------------------
// Shared typography / layout presets
// ---------------------------------------------------------------------------

/** Default system stack — neutral, safe fallback for every platform. */
const SYSTEM_SANS =
  'system-ui, -apple-system, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif';
const SYSTEM_MONO =
  'ui-monospace, "SF Mono", "Cascadia Mono", Menlo, Consolas, monospace';

const DEFAULT_TYPOGRAPHY: ThemeTypography = {
  fontSans: SYSTEM_SANS,
  fontMono: SYSTEM_MONO,
  baseSize: "15px",
  lineHeight: "1.55",
  letterSpacing: "0",
};

const DEFAULT_LAYOUT: ThemeLayout = {
  radius: "0.5rem",
  density: "comfortable",
};

// ---------------------------------------------------------------------------
// Themes
// ---------------------------------------------------------------------------

const AMPLIIA_CUSTOM_CSS = `
:root {
  --ampliia-ink: #050505;
  --ampliia-paper: #fbfbf8;
  --ampliia-paper-2: #f3f2ee;
  --ampliia-muted: #6e6a62;
  --ampliia-muted-strong: #504c45;
  --ampliia-line: rgba(5, 5, 5, 0.12);
  --ampliia-line-strong: rgba(5, 5, 5, 0.22);
  --ampliia-brand: #0c0a92;
  --ampliia-brand-soft: rgba(12, 10, 146, 0.075);
}

body {
  background: var(--ampliia-paper);
}

[data-layout-variant="standard"] {
  color: var(--ampliia-ink) !important;
  background: var(--ampliia-paper) !important;
  text-transform: none;
}

[data-layout-variant="standard"].uppercase {
  text-transform: none !important;
}

[data-layout-variant="standard"] .font-mondwest,
[data-layout-variant="standard"] .font-expanded,
[data-layout-variant="standard"] .font-compressed {
  font-family: var(--theme-font-sans) !important;
  letter-spacing: 0 !important;
}

[data-layout-variant="standard"] .font-courier,
[data-layout-variant="standard"] .font-mono,
[data-layout-variant="standard"] .font-mono-ui {
  font-family: var(--theme-font-mono) !important;
}

[data-layout-variant="standard"] .blend-lighter {
  mix-blend-mode: normal;
}

[data-layout-variant="standard"] header h1,
[data-layout-variant="standard"] header .font-bold.text-midground,
[data-layout-variant="standard"] #app-sidebar > div:first-child .font-bold.text-midground {
  color: var(--ampliia-brand) !important;
  mix-blend-mode: normal !important;
  opacity: 1 !important;
}

[data-layout-variant="standard"] header,
[data-layout-variant="standard"] #app-sidebar {
  background: rgba(251, 251, 248, 0.9) !important;
  border-color: var(--ampliia-line) !important;
  backdrop-filter: blur(18px);
}

[data-layout-variant="standard"] #app-sidebar {
  box-shadow: none;
}

[data-layout-variant="standard"] #app-sidebar > div:first-child {
  min-height: 76px;
  padding: 0 18px;
}

[data-layout-variant="standard"] #app-sidebar nav {
  border-top-color: var(--ampliia-line);
}

[data-layout-variant="standard"] a[aria-current="page"],
[data-layout-variant="standard"] nav a:hover {
  color: var(--ampliia-brand) !important;
}

[data-layout-variant="standard"] .opacity-60 {
  opacity: 0.76 !important;
}

[data-layout-variant="standard"] .text-midground,
[data-layout-variant="standard"] .text-card-foreground,
[data-layout-variant="standard"] .text-foreground {
  color: var(--ampliia-ink) !important;
}

[data-layout-variant="standard"] .text-muted-foreground,
[data-layout-variant="standard"] .text-muted-foreground\\/90,
[data-layout-variant="standard"] .text-muted-foreground\\/80,
[data-layout-variant="standard"] .text-muted-foreground\\/70,
[data-layout-variant="standard"] .text-muted-foreground\\/60,
[data-layout-variant="standard"] .text-muted-foreground\\/50,
[data-layout-variant="standard"] .text-muted-foreground\\/40,
[data-layout-variant="standard"] .text-midground\\/85,
[data-layout-variant="standard"] .text-midground\\/80,
[data-layout-variant="standard"] .text-midground\\/75,
[data-layout-variant="standard"] .text-midground\\/70,
[data-layout-variant="standard"] .text-midground\\/65,
[data-layout-variant="standard"] .text-midground\\/60,
[data-layout-variant="standard"] .text-midground\\/55,
[data-layout-variant="standard"] .text-midground\\/50,
[data-layout-variant="standard"] .text-midground\\/45,
[data-layout-variant="standard"] .text-midforeground\\/85,
[data-layout-variant="standard"] .text-midforeground\\/75,
[data-layout-variant="standard"] .text-midforeground\\/65,
[data-layout-variant="standard"] .text-midforeground\\/55,
[data-layout-variant="standard"] .text-midforeground\\/45 {
  color: var(--ampliia-muted-strong) !important;
}

[data-layout-variant="standard"] .text-primary {
  color: var(--ampliia-brand) !important;
}

[data-layout-variant="standard"] .text-success,
[data-layout-variant="standard"] .text-emerald-400,
[data-layout-variant="standard"] .text-emerald-500 {
  color: #15803d !important;
}

[data-layout-variant="standard"] .text-warning {
  color: #b45309 !important;
}

[data-layout-variant="standard"] a[aria-current="page"]::before {
  background: var(--ampliia-brand) !important;
}

[data-layout-variant="standard"] .border-current\\/20,
[data-layout-variant="standard"] .border-current\\/10 {
  border-color: var(--ampliia-line) !important;
}

[data-layout-variant="standard"] button,
[data-layout-variant="standard"] input,
[data-layout-variant="standard"] select,
[data-layout-variant="standard"] textarea {
  border-radius: 2px !important;
}

[data-layout-variant="standard"] input,
[data-layout-variant="standard"] select,
[data-layout-variant="standard"] textarea {
  background: rgba(255, 255, 255, 0.58) !important;
  border-color: var(--ampliia-line-strong) !important;
  color: var(--ampliia-ink) !important;
}

[data-layout-variant="standard"] input:focus,
[data-layout-variant="standard"] select:focus,
[data-layout-variant="standard"] textarea:focus {
  border-color: var(--ampliia-brand) !important;
  box-shadow: inset 0 -2px 0 var(--ampliia-brand) !important;
}

[data-layout-variant="standard"] .shadow-2xl,
[data-layout-variant="standard"] [class*="shadow-"] {
  box-shadow: none !important;
}

[data-layout-variant="standard"] .bg-midground,
[data-layout-variant="standard"] .bg-foreground {
  background-color: var(--ampliia-ink) !important;
}

[data-layout-variant="standard"] button.bg-midground:hover,
[data-layout-variant="standard"] button.bg-foreground:hover {
  background-color: var(--ampliia-brand) !important;
  border-color: var(--ampliia-brand) !important;
  color: #ffffff !important;
}
`;

export const defaultTheme: DashboardTheme = {
  name: "default",
  label: "Ampliia",
  description: "Light paper, grid lines, black text, and Ampliia blue",
  palette: {
    background: { hex: "#fbfbf8", alpha: 1 },
    midground: { hex: "#050505", alpha: 1 },
    foreground: { hex: "#050505", alpha: 1 },
    warmGlow: "rgba(12, 10, 146, 0.06)",
    noiseOpacity: 0,
  },
  typography: {
    ...DEFAULT_TYPOGRAPHY,
    fontSans: `"Inter", ${SYSTEM_SANS}`,
    fontMono: SYSTEM_MONO,
    fontUrl:
      "https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap",
    letterSpacing: "0",
  },
  layout: {
    ...DEFAULT_LAYOUT,
    radius: "2px",
  },
  assets: {
    bg:
      "linear-gradient(90deg, rgba(5,5,5,.035) 1px, transparent 1px), linear-gradient(180deg, rgba(5,5,5,.028) 1px, transparent 1px), radial-gradient(circle at 70% 8%, rgba(12,10,146,.06), transparent 34rem)",
  },
  componentStyles: {
    backdrop: {
      baseBlendMode: "normal",
      fillerBlendMode: "normal",
      fillerOpacity: "1",
      backgroundSize: "72px 72px, 72px 72px, auto",
      backgroundPosition: "0 0, 0 0, center",
      warmOpacity: "0",
    },
    card: {
      border: "1px solid rgba(5, 5, 5, 0.12)",
      background: "rgba(251, 251, 248, 0.92)",
      boxShadow: "none",
    },
  },
  colorOverrides: {
    card: "rgba(251, 251, 248, 0.92)",
    cardForeground: "#050505",
    popover: "rgba(251, 251, 248, 0.98)",
    popoverForeground: "#050505",
    primary: "#0c0a92",
    primaryForeground: "#ffffff",
    secondary: "rgba(255, 255, 255, 0.42)",
    secondaryForeground: "#050505",
    muted: "rgba(5, 5, 5, 0.06)",
    mutedForeground: "#504c45",
    accent: "rgba(12, 10, 146, 0.075)",
    accentForeground: "#0c0a92",
    border: "rgba(5, 5, 5, 0.12)",
    input: "rgba(5, 5, 5, 0.22)",
    ring: "#0c0a92",
    success: "#15803d",
    warning: "#b45309",
  },
  customCSS: AMPLIIA_CUSTOM_CSS,
};

export const midnightTheme: DashboardTheme = {
  name: "midnight",
  label: "Midnight",
  description: "Deep blue-violet with cool accents",
  palette: {
    background: { hex: "#0a0a1f", alpha: 1 },
    midground: { hex: "#d4c8ff", alpha: 1 },
    foreground: { hex: "#ffffff", alpha: 0 },
    warmGlow: "rgba(167, 139, 250, 0.32)",
    noiseOpacity: 0.8,
  },
  typography: {
    ...DEFAULT_TYPOGRAPHY,
    fontSans: `"Inter", ${SYSTEM_SANS}`,
    fontMono: `"JetBrains Mono", ${SYSTEM_MONO}`,
    fontUrl:
      "https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500;700&display=swap",
    letterSpacing: "-0.005em",
  },
  layout: {
    ...DEFAULT_LAYOUT,
    radius: "0.75rem",
  },
};

export const emberTheme: DashboardTheme = {
  name: "ember",
  label: "Ember",
  description: "Warm crimson and bronze — forge vibes",
  palette: {
    background: { hex: "#1a0a06", alpha: 1 },
    midground: { hex: "#ffd8b0", alpha: 1 },
    foreground: { hex: "#ffffff", alpha: 0 },
    warmGlow: "rgba(249, 115, 22, 0.38)",
    noiseOpacity: 1,
  },
  typography: {
    ...DEFAULT_TYPOGRAPHY,
    fontSans: `"Spectral", Georgia, "Times New Roman", serif`,
    fontMono: `"IBM Plex Mono", ${SYSTEM_MONO}`,
    fontUrl:
      "https://fonts.googleapis.com/css2?family=Spectral:wght@400;500;600;700&family=IBM+Plex+Mono:wght@400;500;700&display=swap",
  },
  layout: {
    ...DEFAULT_LAYOUT,
    radius: "0.25rem",
  },
  colorOverrides: {
    destructive: "#c92d0f",
    warning: "#f97316",
  },
};

export const monoTheme: DashboardTheme = {
  name: "mono",
  label: "Mono",
  description: "Clean grayscale — minimal and focused",
  palette: {
    background: { hex: "#0e0e0e", alpha: 1 },
    midground: { hex: "#eaeaea", alpha: 1 },
    foreground: { hex: "#ffffff", alpha: 0 },
    warmGlow: "rgba(255, 255, 255, 0.1)",
    noiseOpacity: 0.6,
  },
  typography: {
    ...DEFAULT_TYPOGRAPHY,
    fontSans: `"IBM Plex Sans", ${SYSTEM_SANS}`,
    fontMono: `"IBM Plex Mono", ${SYSTEM_MONO}`,
    fontUrl:
      "https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@400;500;600&family=IBM+Plex+Mono:wght@400;500&display=swap",
  },
  layout: {
    ...DEFAULT_LAYOUT,
    radius: "0",
  },
};

export const cyberpunkTheme: DashboardTheme = {
  name: "cyberpunk",
  label: "Cyberpunk",
  description: "Neon green on black — matrix terminal",
  palette: {
    background: { hex: "#040608", alpha: 1 },
    midground: { hex: "#9bffcf", alpha: 1 },
    foreground: { hex: "#ffffff", alpha: 0 },
    warmGlow: "rgba(0, 255, 136, 0.22)",
    noiseOpacity: 1.2,
  },
  typography: {
    ...DEFAULT_TYPOGRAPHY,
    fontSans: `"Share Tech Mono", "JetBrains Mono", ${SYSTEM_MONO}`,
    fontMono: `"Share Tech Mono", "JetBrains Mono", ${SYSTEM_MONO}`,
    fontUrl:
      "https://fonts.googleapis.com/css2?family=Share+Tech+Mono&family=JetBrains+Mono:wght@400;700&display=swap",
  },
  layout: {
    ...DEFAULT_LAYOUT,
    radius: "0",
  },
  colorOverrides: {
    success: "#00ff88",
    warning: "#ffd700",
    destructive: "#ff0055",
  },
};

export const roseTheme: DashboardTheme = {
  name: "rose",
  label: "Rosé",
  description: "Soft pink and warm ivory — easy on the eyes",
  palette: {
    background: { hex: "#1a0f15", alpha: 1 },
    midground: { hex: "#ffd4e1", alpha: 1 },
    foreground: { hex: "#ffffff", alpha: 0 },
    warmGlow: "rgba(249, 168, 212, 0.3)",
    noiseOpacity: 0.9,
  },
  typography: {
    ...DEFAULT_TYPOGRAPHY,
    fontSans: `"Fraunces", Georgia, serif`,
    fontMono: `"DM Mono", ${SYSTEM_MONO}`,
    fontUrl:
      "https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,400;9..144,500;9..144,600&family=DM+Mono:wght@400;500&display=swap",
  },
  layout: {
    ...DEFAULT_LAYOUT,
    radius: "1rem",
  },
};

/**
 * Same look as ``defaultTheme`` but with a larger root font size, looser
 * line-height, and ``spacious`` density so every rem-based size in the
 * dashboard scales up. For users who find the default 15px UI too dense.
 */
export const defaultLargeTheme: DashboardTheme = {
  name: "default-large",
  label: "Ampliia (Large)",
  description: "Ampliia with bigger fonts and roomier spacing",
  palette: defaultTheme.palette,
  typography: {
    ...defaultTheme.typography,
    baseSize: "18px",
    lineHeight: "1.65",
  },
  layout: {
    ...defaultTheme.layout,
    density: "spacious",
  },
  assets: defaultTheme.assets,
  componentStyles: defaultTheme.componentStyles,
  colorOverrides: defaultTheme.colorOverrides,
  customCSS: defaultTheme.customCSS,
};

export const BUILTIN_THEMES: Record<string, DashboardTheme> = {
  default: defaultTheme,
  "default-large": defaultLargeTheme,
  midnight: midnightTheme,
  ember: emberTheme,
  mono: monoTheme,
  cyberpunk: cyberpunkTheme,
  rose: roseTheme,
};
