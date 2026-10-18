# Glyph Hold 2 identity and dashboard design

The dashboard implements the approved neutral/teal preview using shared styles in `src/design-system.css`. Page backgrounds use #e9eeec, navigation #dce5e1, surfaces #f7f9f7, text #253b35, and the primary accent #466c60. Standard controls are34px high, supporting text12px, body13px and page titles25px.

The logo is saved as `public/glyphhold-logo.png`, a transparent PNG generated with the built-in image generation tool. It is used in the sidebar, sign-in/setup screen and favicon. The original generated alpha channel is preserved.

## Generation prompt

Use case: logo-brand. Create a single professional app logo symbol for Glyph Hold, a shared agent memory application. Transparent background. A distinctive simple geometric glyph suggesting a protected, held memory: interlocking angular G and a small central stored tile, elegant compact hexagonal silhouette. Flat vector-like mark, clean precise edges, generous negative space, bold enough to remain legible at32px. One solid muted deep teal #466c60, optional negative space only. No text, no lettering wordmark, no gradients, no shadows, no3D, no decorative surroundings. Centered isolated symbol occupying80percent of square canvas. Calm modern restrained utility-software identity.

## Local validation

The image is built as glyphhold:gh2-local-test and served by the isolated GH2 instance onlocalhost5996. Browser checks covered all nine pages at1500,900,768 and390px. Visual reviewers inspected desktop/tablet and phone layouts. Actual workflows tested memory creation/archive, fictional secret creation/reveal/removal, schedule visibility, Settings tabs and category dialog navigation. The originalGH1 instance on5995 remains separate.

The account used for visual QA was temporary. Test secrets were removed; temporary memory records were archived. Existing user accounts, memory records and Codex subscription sign-in were preserved.
