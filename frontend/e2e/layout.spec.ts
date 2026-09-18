/**
 * The home page's shell, measured in a browser (#115).
 *
 * Everything here needs a layout engine, which is why it is not in the jsdom suite: jsdom gives
 * every element a height of zero and a `scrollHeight` of zero, so "nothing scrolls" passes there
 * against a page that scrolls, and "the columns are the same height" passes against no columns at
 * all. A test that cannot fail is worse than no test, because it is quoted as evidence.
 *
 * The API is stubbed from the same fixtures the jsdom suite uses, so a failure here means the
 * layout moved rather than the sea did, and no backend has to be running.
 */

import { expect, test } from '@playwright/test';

import { DESKTOP, NARROW } from '../playwright.config';
import { currentConditions, forecast, trackRecord } from '../src/test/handlers';

/** The fixtures, served to the page. The paths are the backend's, and `**` covers the origin —
 * the app reads `VITE_API_BASE` and falls back to `localhost:8000`, which is not this server. */
test.beforeEach(async ({ page }) => {
  await page.route('**/api/conditions/current', (route) =>
    route.fulfill({ json: currentConditions }),
  );
  await page.route('**/api/conditions/forecast', (route) => route.fulfill({ json: forecast }));
  await page.route('**/api/track-record', (route) => route.fulfill({ json: trackRecord }));
});

/** The page, loaded and settled, with the conditions actually on it. Every measurement below
 * depends on the content being there — measuring a loading state would report the height of the
 * word "Loading". */
async function loadHome(page: import('@playwright/test').Page) {
  await page.goto('/');
  await expect(page.getByRole('group', { name: 'Swell height' })).toBeVisible();
  return {
    forecast: page.locator('.home-forecast'),
    map: page.locator('.home-map'),
    slot: page.locator('.map-slot'),
  };
}

test.describe(`the two columns, at ${DESKTOP.width}x${DESKTOP.height}`, () => {
  test('stand at the same height', async ({ page }) => {
    const { forecast, map } = await loadHome(page);

    const left = (await forecast.boundingBox())!;
    const right = (await map.boundingBox())!;

    // Equal to the pixel, because they are grid tracks in one row rather than two things that
    // happen to be about as tall as each other. A tolerance here would hide the bug it exists to
    // catch: a map that is *nearly* the column's height is a map that has stopped being tied to
    // it.
    expect(Math.round(right.height)).toBe(Math.round(left.height));
    expect(Math.round(right.y)).toBe(Math.round(left.y));
  });

  test('give neither column a scrollbar of its own', async ({ page }) => {
    const { forecast, map } = await loadHome(page);

    for (const column of [forecast, map]) {
      const overflow = await column.evaluate((el) => {
        const style = getComputedStyle(el);
        return {
          x: style.overflowX,
          y: style.overflowY,
          scrolls: el.scrollHeight > el.clientHeight + 1,
        };
      });

      // `visible` both ways, and nothing actually overflowing its own box. A column that
      // scrolled independently would slide its half of the page past the other, which is the
      // failure a pinned map was rejected for.
      expect(overflow.x).toBe('visible');
      expect(overflow.y).toBe('visible');
      expect(overflow.scrolls).toBe(false);
    }
  });

  test('keep their proportion as the window resizes', async ({ page }) => {
    const { forecast, map } = await loadHome(page);
    const ratios: number[] = [];

    for (const width of [1280, DESKTOP.width, 1920]) {
      await page.setViewportSize({ width, height: DESKTOP.height });
      const left = (await forecast.boundingBox())!;
      const right = (await map.boundingBox())!;
      ratios.push(right.width / (left.width + right.width));
    }

    // The split is declared in fractions, so the map's share of the width is the same at every
    // desktop width rather than at the one it was designed on. Loose to two decimal places: the
    // gap between the columns is a fixed length, so its share of the total moves a little as the
    // window grows, and pinning this tighter would be asserting arithmetic rather than layout.
    for (const ratio of ratios) {
      expect(ratio).toBeCloseTo(ratios[0]!, 2);
    }

    // And the map is the smaller share, which is the design's ordering: the figures are what a
    // reader came for and the map is the context around them.
    expect(ratios[0]!).toBeLessThan(0.5);
  });

  test('do not scroll the page horizontally', async ({ page }) => {
    await loadHome(page);

    // The hourly table is wider than its column and scrolls inside its own box. If that ever
    // stops being true it takes the whole page sideways with it, which is the one scroll a
    // desktop layout can never explain away.
    const sideways = await page.evaluate(
      () => document.documentElement.scrollWidth > window.innerWidth + 1,
    );
    expect(sideways).toBe(false);
  });
});

test.describe('the map slot', () => {
  test('says it is a placeholder rather than resembling a map', async ({ page }) => {
    const { slot } = await loadHome(page);

    await expect(slot).toBeVisible();
    await expect(slot).toContainText('Map');
    await expect(slot).toContainText(/placeholder/i);

    // Nothing drawn. A placeholder that resembles the thing it stands in for is how a half-built
    // feature gets mistaken for a finished one.
    expect(await slot.locator('svg, canvas, img').count()).toBe(0);

    // And legible without scrolling to it. `toBeVisible` only means the box is non-empty, so it
    // passes happily on a label centred a thousand pixels down a very tall slot — which is what
    // this page did until the label was moved to the top. "Visibly a placeholder" has to mean
    // visible on arrival, or the page opens on what reads as an empty panel.
    const label = (await slot.locator('.map-slot-what').boundingBox())!;
    expect(label.y + label.height).toBeLessThanOrEqual(DESKTOP.height);
  });

  test('is present before the conditions arrive, so the page does not jump', async ({ page }) => {
    // A column that appeared only on success would move the page at the moment a reader is
    // deciding whether to trust it.
    await page.route('**/api/conditions/current', (route) => route.fulfill({ status: 500 }));
    await page.goto('/');

    await expect(page.getByRole('alert')).toBeVisible();
    await expect(page.locator('.map-slot')).toBeVisible();
  });
});

test.describe(`narrow widths, at ${NARROW.width}x${NARROW.height}`, () => {
  // Not the phone design, which is separate work and not part of v2. This is the promise that the
  // phone is not broken while it waits for one.
  test.use({ viewport: NARROW });

  test('stack to one column, forecast first', async ({ page }) => {
    const { forecast, map } = await loadHome(page);

    const left = (await forecast.boundingBox())!;
    const right = (await map.boundingBox())!;

    // Stacked, not squeezed: the map starts below where the forecast ends.
    expect(right.y).toBeGreaterThanOrEqual(left.y + left.height - 1);
    expect(Math.round(right.width)).toBe(Math.round(left.width));
  });

  test('render every element, with nothing off the side of the screen', async ({ page }) => {
    await loadHome(page);

    const sideways = await page.evaluate(
      () => document.documentElement.scrollWidth > window.innerWidth + 1,
    );
    expect(sideways).toBe(false);

    // The things a reader would notice missing. Legible rather than merely present: each is
    // visible, which in Playwright means it has a non-empty box.
    await expect(page.getByRole('heading', { name: 'NazareNow' })).toBeVisible();
    await expect(page.getByRole('group', { name: 'Swell height' })).toBeVisible();
    await expect(page.getByRole('navigation', { name: 'Pages' })).toBeVisible();
    await expect(page.locator('.map-slot')).toBeVisible();
    await expect(page.getByTestId('provenance')).toBeVisible();
  });
});

test.describe('how tall the page is, which is the promise not yet kept', () => {
  test(`is under twice the ${DESKTOP.height}px viewport, and will have to reach one`, async ({
    page,
  }) => {
    await loadHome(page);

    const height = await page.evaluate(() => document.documentElement.scrollHeight);

    /**
     * **#115 builds the shell; it does not make the page fit.** The contents of the left column
     * are still v1's — ten condition tiles in three groups, the windows panel, the day cards —
     * and the tickets that shorten them are #116 (four gated tiles) and #117 (one row per day).
     * At the time of writing this page is about 1.9 viewports tall.
     *
     * So this is a ratchet rather than the promise: the page may not get dramatically taller
     * while it waits. The ceiling is generous on purpose — it has to survive the difference
     * between the font metrics on a developer's machine and the ones in CI, and a bound tight
     * enough to flake would be removed the first time it did.
     *
     * **#117 replaces the 2 with a 1**, at which point this test becomes the no-scroll promise
     * itself, and `expect(height).toBeLessThanOrEqual(DESKTOP.height)` is the whole of it.
     */
    expect(height).toBeLessThanOrEqual(DESKTOP.height * 2);
  });
});
