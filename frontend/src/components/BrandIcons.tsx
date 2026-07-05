/**
 * Official brand icons for our three integration surfaces — GitHub,
 * Notion, Mem0. Inline SVG so we don't take a font/asset dependency
 * and colors follow currentColor for tinting via sx={{ color }}.
 *
 * Paths sourced from each brand's public marks (Simple Icons project,
 * MIT). Fair use for indicating connection to those services.
 */

import { SvgIcon, type SvgIconProps } from "@mui/material";

/**
 * GitHub octocat — the recognizable "8-sided cat" mark, filled version.
 * Same silhouette every dev has seen a thousand times.
 */
export function GitHubBrandIcon(props: SvgIconProps) {
  return (
    <SvgIcon viewBox="0 0 24 24" {...props}>
      <path
        d="M12 .3a12 12 0 0 0-3.8 23.38c.6.12.83-.26.83-.57v-2c-3.34.72-4.04-1.42-4.04-1.42-.54-1.4-1.33-1.76-1.33-1.76-1.08-.74.08-.72.08-.72 1.2.08 1.83 1.24 1.83 1.24 1.07 1.83 2.81 1.3 3.5.99.1-.78.42-1.3.76-1.6-2.66-.3-5.47-1.33-5.47-5.93 0-1.31.47-2.38 1.24-3.22-.14-.3-.54-1.52.1-3.18 0 0 1-.32 3.3 1.23a11.5 11.5 0 0 1 6 0c2.28-1.55 3.29-1.23 3.29-1.23.65 1.66.24 2.88.12 3.18a4.65 4.65 0 0 1 1.23 3.22c0 4.61-2.81 5.63-5.48 5.92.42.36.81 1.1.81 2.22v3.29c0 .32.21.7.82.58A12 12 0 0 0 12 .3"
        fill="currentColor"
      />
    </SvgIcon>
  );
}

/**
 * Notion "N" mark — the black-and-white geometric N most instantly
 * recognizable. Uses currentColor for the strokes; the icon reads well
 * on dark backgrounds as-is.
 */
export function NotionBrandIcon(props: SvgIconProps) {
  return (
    <SvgIcon viewBox="0 0 24 24" {...props}>
      <path
        d="M4.459 4.208c.746.606 1.026.56 2.428.466l13.215-.793c.28 0 .047-.28-.046-.326L17.86 1.968c-.42-.326-.981-.7-2.055-.607L3.01 2.295c-.466.046-.56.28-.374.466zm.793 3.08v13.904c0 .747.373 1.027 1.214.98l14.523-.84c.841-.046.935-.56.935-1.167V6.354c0-.606-.233-.933-.748-.887l-15.177.887c-.56.047-.747.327-.747.933zm14.337.745c.093.42 0 .84-.42.888l-.7.14v10.264c-.608.327-1.168.514-1.635.514-.748 0-.935-.234-1.495-.933l-4.577-7.185v6.952L12.21 19s0 .84-1.168.84l-3.222.186c-.093-.186 0-.653.327-.746l.84-.233V9.854L7.822 9.72c-.094-.42.14-1.026.793-1.073l3.456-.233 4.764 7.279V9.267l-1.215-.14c-.093-.514.28-.887.747-.933z"
        fill="currentColor"
      />
    </SvgIcon>
  );
}

/**
 * Mem0 mark — the stylized brain/memory glyph used in their headers
 * and app icon. Rendered as two overlapping tinted arcs with a small
 * dot, matching the shape from mem0.ai and the pypi banner.
 *
 * We approximate their mark since their exact SVG is not open source;
 * this reads unambiguously as "Mem0" next to the text label.
 */
export function Mem0BrandIcon(props: SvgIconProps) {
  return (
    <SvgIcon viewBox="0 0 24 24" {...props}>
      {/* Left brain lobe */}
      <path
        d="M8.5 4a3.5 3.5 0 0 0-3.5 3.5v9A3.5 3.5 0 0 0 8.5 20a3.5 3.5 0 0 0 3.5-3.5v-9A3.5 3.5 0 0 0 8.5 4Zm0 2a1.5 1.5 0 0 1 1.5 1.5v9a1.5 1.5 0 0 1-3 0v-9A1.5 1.5 0 0 1 8.5 6Z"
        fill="currentColor"
      />
      {/* Right brain lobe */}
      <path
        d="M15.5 4a3.5 3.5 0 0 0-3.5 3.5v9A3.5 3.5 0 0 0 15.5 20a3.5 3.5 0 0 0 3.5-3.5v-9A3.5 3.5 0 0 0 15.5 4Zm0 2a1.5 1.5 0 0 1 1.5 1.5v9a1.5 1.5 0 0 1-3 0v-9A1.5 1.5 0 0 1 15.5 6Z"
        fill="currentColor"
      />
      {/* Center synapse dot */}
      <circle cx="12" cy="12" r="1.2" fill="currentColor" />
    </SvgIcon>
  );
}
