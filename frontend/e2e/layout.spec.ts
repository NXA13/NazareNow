/**
 * The home page's shell, measured in a browser (#115).
 *
 * Everything here needs a layout engine, which is why it is not in the jsdom suite: jsdom gives
 * every element a height of zero and a `scrollHeight` of zero, so "nothing scrolls" passes there
 * against a page that scrolls, and "the columns are the same height" passes against no columns at
 * all. A test that cannot fail is worse than no test, because it is quoted as evidence.
 *
 * The API is stubbed from the same table the jsdom suite uses, so a failure here means the layout
 * moved rather than the sea did, and no backend has to be running.
 */

import { expect, test, type Page } from '@playwright/test';

import { DESKTOP, NARROW } from '../playwright.config';
import { FIXTURE_BY_PATH, longForecast } from '../src/test/handlers';

/**
 * The whole API surface, stubbed from the shared table.
 *
 * Every path, not only the ones this file's pages happen to fetch: the stub describes what the
 * backend answers, and a spec that stubbed only what it currently needs would let a later test
 * hit the network without anybody noticing.
 */
test.beforeEach(async ({ page }) => {
  for (const [path, body] of Object.entries(FIXTURE_BY_PATH)) {
    await page.route(`**${path}`, (route) => route.fulfill({ json: body }));
  }

  // The forecast, at the length the provider can actually send. The shared table's three-day
  // forecast is right for behaviour and wrong for measurement: a page proved to lay out at three
  // days says nothing about the ten a reader sees today or the sixteen the backend asks for, and
  // "any layout that assumes a fixed count is a layout that breaks silently" is the design
  // spec's own warning.
  await page.route('**/api/conditions/forecast', (route) => route.fulfill({ json: longForecast }));
});

/** The page, loaded and settled, with the conditions actually on it. Every measurement below
 * depends on the content being there — measuring a loading state would report the height of the
 * word "Loading". */
async function loadHome(page: Page) {
  await page.goto('/');
  await expect(page.getByRole('group', { name: 'Swell height' })).toBeVisible();
  return {
    left: page.locator('.home-forecast'),
    right: page.locator('.home-map'),
    // The slot rather than its grid track. The track is stretched by the grid whatever the slot
    // does, so a measurement taken on the track cannot see the panel inside it collapse.
    slot: page.locator('.map-slot'),
  };
}

/** Whether the page — not an element inside it — runs off the side of the screen. */
async function scrollsSideways(page: Page) {
  return page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth + 1);
}

/** The viewport the browser is really at, so an assertion cannot check one size while the
 * describe block's name reports another. */
async function viewport(page: Page) {
  const size = page.viewportSize();
  expect(size, 'the tests measure against a real viewport').not.toBeNull();
  return size!;
}

test.describe(`the two columns, at ${DESKTOP.width}x${DESKTOP.height}`, () => {
  test('stand at the same height, and the map fills its column', async ({ page }) => {
    const { left, right, slot } = await loadHome(page);

    const forecastBox = (await left.boundingBox())!;
    const trackBox = (await right.boundingBox())!;
    const slotBox = (await slot.boundingBox())!;

    // Equal to the pixel, because these are grid tracks in one row rather than two things that
    // happen to be about as tall as each other.
    expect(Math.round(trackBox.height)).toBe(Math.round(forecastBox.height));
    expect(Math.round(trackBox.y)).toBe(Math.round(forecastBox.y));

    // And the *slot* is measured, not only its track. The grid stretches the track whatever the
    // panel inside it does, so asserting on the track alone passes with `height: 100%` deleted
    // from `.map-slot` and the dashed box collapsed to the height of its own two lines of text.
    // "The map fills the right column and matches its height" is a claim about the panel a
    // reader sees.
    expect(Math.round(slotBox.height)).toBe(Math.round(forecastBox.height));
    expect(Math.round(slotBox.width)).toBe(Math.round(trackBox.width));
  });

  test('give neither column a scrollbar of its own', async ({ page }) => {
    const { left, right } = await loadHome(page);

    // First, that there is a two-column grid at all. Without this the overflow assertions below
    // pass against a page with no `.home` rules whatsoever — `visible` is CSS's initial value,
    // so "no column scrolls" is trivially true of a stylesheet that never ran.
    await expect(page.locator('.home')).toHaveCSS('display', 'grid');
    const columns = await page.locator('.home').evaluate((el) => {
      return getComputedStyle(el).gridTemplateColumns.split(/\s+/).filter(Boolean).length;
    });
    expect(columns).toBe(2);

    for (const column of [left, right]) {
      const overflow = await column.evaluate((el) => {
        const style = getComputedStyle(el);
        return {
          x: style.overflowX,
          y: style.overflowY,
          scrolls: el.scrollHeight > el.clientHeight + 1,
        };
      });

      // A column that scrolled independently would slide its half of the page past the other,
      // which is the failure a pinned map was rejected for.
      expect(overflow.x).toBe('visible');
      expect(overflow.y).toBe('visible');
      expect(overflow.scrolls).toBe(false);
    }
  });

  test('keep their proportion as the window resizes', async ({ page }) => {
    const { left, right } = await loadHome(page);

    /** Desktop widths worth holding the proportion at: a small laptop, the viewport the
     * no-scroll promise is made at, and a large monitor. */
    const widths = [1280, DESKTOP.width, 1920];
    const ratios: number[] = [];

    for (const width of widths) {
      await page.setViewportSize({ width, height: DESKTOP.height });
      const forecastBox = (await left.boundingBox())!;
      const trackBox = (await right.boundingBox())!;
      ratios.push(trackBox.width / (forecastBox.width + trackBox.width));
    }

    const [first, ...rest] = ratios;

    // Each of the others against the first, so every comparison is between two different
    // measurements. The split is declared in fractions, so the map's share is the same at every
    // desktop width rather than at the one it was designed on. Loose to two decimal places: the
    // gap between the columns is a fixed length, so its share of the total moves a little as the
    // window grows, and pinning this tighter would be asserting arithmetic rather than layout.
    expect(rest).toHaveLength(widths.length - 1);
    for (const ratio of rest) {
      expect(ratio).toBeCloseTo(first!, 2);
    }

    // And the map is the smaller share, which is the design's ordering: the figures are what a
    // reader came for and the map is the context around them.
    expect(first!).toBeLessThan(0.5);
  });

  test('do not scroll the page horizontally', async ({ page }) => {
    await loadHome(page);

    // The hourly table is wider than its column and scrolls inside its own box. If that ever
    // stops being true it takes the whole page sideways with it, which is the one scroll a
    // desktop layout can never explain away.
    expect(await scrollsSideways(page)).toBe(false);
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
    expect(label.y + label.height).toBeLessThanOrEqual((await viewport(page)).height);
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
    const { left, right } = await loadHome(page);

    const forecastBox = (await left.boundingBox())!;
    const trackBox = (await right.boundingBox())!;

    // Stacked, not squeezed: the map starts below where the forecast ends.
    expect(trackBox.y).toBeGreaterThanOrEqual(forecastBox.y + forecastBox.height - 1);
    expect(Math.round(trackBox.width)).toBe(Math.round(forecastBox.width));
  });

  test('render every element, with nothing off the side of the screen', async ({ page }) => {
    await loadHome(page);

    expect(await scrollsSideways(page)).toBe(false);

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
  test('does not fit yet, and #117 is where it has to', async ({ page }) => {
    await loadHome(page);

    const { height: viewportHeight } = await viewport(page);
    const height = await page.evaluate(() => document.documentElement.scrollHeight);

    /**
     * **#115 builds the shell; it does not make the page fit.** The left column still holds v1's
     * contents — ten condition tiles in three groups, the windows panel, the day cards — and the
     * tickets that shorten them are #116 (four gated tiles) and #117 (one row per day), whose own
     * criteria already say the column must "still satisfy the no-scroll promise".
     *
     * **This asserts the shortfall rather than a ceiling on it**, and the difference matters. A
     * ceiling — "under two viewports" — was the first thing written here, and it was measuring
     * the fixture rather than the page: three days of rows fit under it and sixteen do not, so
     * the bound said more about how long the test's forecast was than about the layout. A count
     * the page must never assume is exactly what the design spec warns against assuming.
     *
     * What is true at any count is that the page does not fit yet, and more days only make it
     * more true. So that is what is asserted, and it makes the test retire itself: the day #116
     * or #117 brings the page under a viewport this fails, and whoever is holding it then
     * replaces it with `toBeLessThanOrEqual(viewportHeight)` — which is the no-scroll promise,
     * and the whole of it. A note asking a later ticket to remember is a note nobody reads; a
     * failing test is not.
     */
    expect(height).toBeGreaterThan(viewportHeight);
  });
});
