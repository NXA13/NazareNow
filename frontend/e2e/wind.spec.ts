/**
 * The wind, in a real browser (#123).
 *
 * Two of this ticket's acceptance criteria cannot be seen in jsdom, which gives every element
 * no size and resolves no cascade:
 *
 * - **reduced motion gives a still map that still shows direction.** `Wind.test.tsx` can assert
 *   the markup; only a browser can say whether the animation is actually off, and only with
 *   the preference actually set.
 * - **the darts are positioned by the cascade they ship with**, not by the inline transform
 *   alone. A CSS `transform` animation on the dart group would override its `transform`
 *   attribute outright — every dart piled at the origin, pointing east, animating convincingly.
 *   That is the specific mistake this file exists to catch.
 */

import { expect, test } from '@playwright/test';

import { FIXTURE_BY_PATH } from '../src/test/handlers';

async function loadMap(page: import('@playwright/test').Page) {
  for (const [path, body] of Object.entries(FIXTURE_BY_PATH)) {
    await page.route(`**${path}`, (route) => route.fulfill({ json: body }));
  }
  await page.goto('/');
  await expect(page.locator('svg.bathymetry .wind-dart').first()).toBeVisible();
}

test.describe('the wind darts', () => {
  test('draws one per fetched point and spreads them across the frame', async ({ page }) => {
    await loadMap(page);
    // Scoped to the map itself: the legend draws the SAME glyph class on purpose, so a
    // `.map-slot` selector counts its three samples too.
    const darts = page.locator('svg.bathymetry .wind-dart');
    await expect(darts).toHaveCount(25);

    // Positions come from the `transform` attribute through the CTM. If a CSS animation had
    // overridden it, every box below would share one origin — which is what this measures.
    const boxes = await darts.evaluateAll((nodes) =>
      nodes.map((node) => {
        const { x, y } = node.getBoundingClientRect();
        return `${Math.round(x)},${Math.round(y)}`;
      }),
    );
    expect(new Set(boxes).size).toBeGreaterThan(20);
  });

  test('keeps every measured point inside the drawn map', async ({ page }) => {
    // ADR 0015 made the whole frame visible precisely so every fetched point is one a reader
    // can see, and `open_meteo.py` shares the bathymetry's bounds so that "a wind glyph placed
    // from a grid point can never sit outside the drawn map".
    //
    // **The promise is about the point, not the glyph.** `grid_points()` divides by
    // `GRID_SIDE - 1`, so the outer rows and columns land ON the bounds rather than at cell
    // centres — which is the fact ADR 0015 turned on. A dart centred exactly on the southern
    // edge therefore overhangs it by half a glyph and is clipped by the SVG. Nudging it inward
    // would put the dart somewhere the wind was not measured, which is a worse lie than a
    // half-drawn arrow, so the position stays true and this asserts what is actually promised.
    await loadMap(page);
    const svg = (await page.locator('svg.bathymetry').boundingBox())!;
    // The ANCHOR, mapped through the SVG's screen matrix — not the bounding box's centre. The
    // glyph extends backwards from its point, so rotating it moves the box around the anchor
    // and a box centre is a different quantity from the place the wind was measured.
    const centres = await page.locator('svg.bathymetry .wind-dart').evaluateAll((nodes) =>
      nodes.map((node) => {
        const owner = (node as SVGGElement).ownerSVGElement!;
        const point = owner.createSVGPoint();
        point.x = 0;
        point.y = 0;
        const screen = point.matrixTransform((node as SVGGElement).getScreenCTM()!);
        return { x: screen.x, y: screen.y };
      }),
    );
    expect(centres).toHaveLength(25);
    for (const centre of centres) {
      expect(centre.x).toBeGreaterThanOrEqual(svg.x - 1);
      expect(centre.y).toBeGreaterThanOrEqual(svg.y - 1);
      expect(centre.x).toBeLessThanOrEqual(svg.x + svg.width + 1);
      expect(centre.y).toBeLessThanOrEqual(svg.y + svg.height + 1);
    }
  });

  test('drifts, and drifts faster where the wind is stronger', async ({ page }) => {
    await loadMap(page);
    const durations = await page
      .locator('svg.bathymetry .wind-dart path')
      .evaluateAll((nodes) => nodes.map((node) => getComputedStyle(node).animationDuration));
    // `animation-duration: inherit` is what carries the per-dart figure down to the path. If it
    // were dropped, every path here would report the same duration and speed would leave the map.
    expect(new Set(durations).size).toBeGreaterThan(20);
    for (const duration of durations) {
      expect(duration).not.toBe('0s');
    }
  });
});

test.describe('with reduced motion asked for', () => {
  test.use({ reducedMotion: 'reduce' });

  test('stops the drift but keeps the direction', async ({ page }) => {
    await loadMap(page);
    // Scoped to the map itself: the legend draws the SAME glyph class on purpose, so a
    // `.map-slot` selector counts its three samples too.
    const darts = page.locator('svg.bathymetry .wind-dart');
    await expect(darts).toHaveCount(25);

    const animations = await darts
      .locator('path')
      .evaluateAll((nodes) => nodes.map((node) => getComputedStyle(node).animationName));
    expect(animations.every((name) => name === 'none')).toBe(true);

    // Direction survives, because it is in the glyph's bearing rather than in its motion.
    const rotations = await darts.evaluateAll((nodes) =>
      nodes.map((node) => node.getAttribute('transform') ?? ''),
    );
    expect(new Set(rotations.map((t) => /rotate\(([-\d.]+)/.exec(t)?.[1])).size).toBeGreaterThan(
      20,
    );
  });
});
