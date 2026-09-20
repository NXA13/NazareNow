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
// The same reader the contrast script and `ink.test.ts` use, so a hex in the sheet and the
// `rgb()` the browser reports for it compare as the one colour they are.
import { parseColour } from '../scripts/check-contrast.mjs';
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
  // And the forecast, which is a second request that lands a moment after the first. Waiting
  // only for the conditions left the day list still saying "Loading forecast...", and since
  // every measurement below is a separate round trip to the browser, the column could be
  // measured before the days arrived and the map after — reporting two columns of different
  // heights for a grid that had in fact stretched both. The heading rather than a row, so this
  // still waits on a response carrying no days at all.
  await expect(page.getByRole('heading', { name: /^The next \d+ days$/ })).toBeVisible();
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

test.describe(`the day list, at ${DESKTOP.width}x${DESKTOP.height}`, () => {
  test('gives every day a row of its own, the full width of the list', async ({ page }) => {
    await loadHome(page);

    const rows = page.locator('.day');
    // Sixteen, because the fixture is the longest response the provider can send. jsdom already
    // proves the count follows the response; what only a browser can say is that sixteen of them
    // are sixteen rows rather than a grid that happens to hold sixteen cells.
    await expect(rows).toHaveCount(longForecast.days.length);

    const boxes = await rows.evaluateAll((elements) =>
      elements.map((element) => {
        const box = element.getBoundingClientRect();
        return { x: Math.round(box.x), width: Math.round(box.width), y: box.y, height: box.height };
      }),
    );

    const [first, ...rest] = boxes;
    for (const box of rest) {
      // Same left edge and same width: a row, not a cell in a track beside another cell. The
      // grid this replaced put seven days across and three down, and every assertion about a
      // day list that did not measure x passed against it.
      expect(box.x).toBe(first!.x);
      expect(box.width).toBe(first!.width);
    }

    // And each one below the last, with no two sharing a line.
    for (let index = 1; index < boxes.length; index += 1) {
      expect(boxes[index]!.y).toBeGreaterThanOrEqual(
        boxes[index - 1]!.y + boxes[index - 1]!.height,
      );
    }

    // One line each, so the column's height is the row count times a constant. A row that wrapped
    // at this width would make sixteen days taller than sixteen times a row, which is exactly the
    // arithmetic #118 and the no-scroll promise rest on.
    const heights = boxes.map((box) => Math.round(box.height));
    expect(Math.max(...heights)).toBe(Math.min(...heights));
  });

  test('dims the days past the measured archive, under their own heading', async ({ page }) => {
    await loadHome(page);

    // The fixture's archive runs out after its eighth day, as the real one does after seven.
    const beyond = page.locator('.days.beyond .day');
    await expect(beyond).toHaveCount(8);
    await expect(page.getByText(/beyond the measured archive/i)).toBeVisible();

    /** How a row actually renders: its edge, and the colour its height is set in. */
    const inkOf = (rows: ReturnType<typeof page.locator>) =>
      rows.first().evaluate((element) => ({
        border: getComputedStyle(element).borderTopStyle,
        height: getComputedStyle(element.querySelector('.day-swell .value')!).color,
        // The muted token as the browser resolves it, so this compares against the sheet's own
        // quiet colour rather than a hex value copied into a test and left to drift.
        muted: getComputedStyle(document.documentElement).getPropertyValue('--ink-muted').trim(),
      }));

    const dim = await inkOf(beyond);
    const measured = await inkOf(page.locator('.days:not(.beyond) .day'));

    // The height is what is uncertain out here, so the height is what goes quiet.
    expect(dim.height).not.toBe(measured.height);
    expect(parseColour(dim.height)).toEqual(parseColour(dim.muted));
    // And the row is hollow rather than filled, so the difference survives a reader who cannot
    // see one step in a grey. A row that looked like the ones above would present an
    // extrapolation as evidence.
    expect(dim.border).toBe('dashed');
    expect(measured.border).not.toBe('dashed');
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

/**
 * The chrome, on both routes (#128).
 *
 * The header is shared by every page and the `h2` rhythm is set by a bare element selector, so
 * a change made for the forecast column silently reaches the reading page too — which is a
 * different kind of page, bounded by `--measure-page` and made of prose rather than
 * instrument. #128 was reviewed with no recorded check of that page at all, and this is it.
 *
 * These are height assertions, so they can only live here: in jsdom the header is 0px tall and
 * every bound below passes against a header of any size.
 */
async function loadReading(page: Page) {
  await page.goto('/#/how-it-works');
  await expect(page.getByRole('heading', { name: 'Track record' })).toBeVisible();
}

test.describe('the chrome, which both routes share', () => {
  /** A bar, not a block. The stack it replaced was 134px, so the bound is written well clear of
   * a bar and well under what it replaced: this is a guard against the header quietly growing
   * a line back, not a pin on its exact height. */
  const BAR_CEILING = 64;

  test('is a bar on the forecast page, not the block it was', async ({ page }) => {
    await loadHome(page);

    const header = (await page.locator('header').boundingBox())!;
    expect(header.height).toBeLessThanOrEqual(BAR_CEILING);
  });

  test('is the same bar on the reading page, which has its own rhythm', async ({ page }) => {
    await loadReading(page);

    const header = (await page.locator('header').boundingBox())!;
    expect(header.height).toBeLessThanOrEqual(BAR_CEILING);

    // The page it was measured on, rather than the forecast page under a different address.
    // An earlier measurement of this route went to `/how-it-works` instead of `/#/how-it-works`,
    // which a hash router answers with the forecast page, and so reported the home page's
    // numbers twice without anything looking wrong.
    await expect(page.locator('.home')).toHaveCount(0);
    expect(await scrollsSideways(page)).toBe(false);
  });

  test('puts the wordmark, the tagline and the nav on one line', async ({ page }) => {
    await loadHome(page);

    const wordmark = (await page.getByRole('heading', { name: 'NazareNow' }).boundingBox())!;
    const tagline = (await page.locator('.tagline').boundingBox())!;
    const nav = (await page.getByRole('navigation', { name: 'Pages' }).boundingBox())!;

    // One line: all three overlap vertically. Their heights differ, since they are set at three
    // sizes and aligned on the baseline, so this asks that each starts before the wordmark ends
    // rather than that their tops match.
    for (const box of [tagline, nav]) {
      expect(box.y).toBeLessThan(wordmark.y + wordmark.height);
    }

    // And in that order across it, with the nav pushed to the far end rather than following the
    // tagline. This is the `margin-left: auto`, which is the whole of the bar.
    expect(tagline.x).toBeGreaterThan(wordmark.x + wordmark.width - 1);
    expect(nav.x).toBeGreaterThan(tagline.x + tagline.width);
  });
});

test.describe(`the chrome at ${NARROW.width}x${NARROW.height}`, () => {
  test.use({ viewport: NARROW });

  /** Weaker than the three above, and worth saying so: the stacked header this replaced also
   * fit a 390px screen, so this test passes against both and proves nothing about the change.
   * What it guards is the bar's one new failure mode — three things asked to share a line on a
   * screen too narrow for them. It holds because the header wraps; delete the `flex-wrap` and
   * this is what fails. */
  test('wraps rather than running off either page', async ({ page }) => {
    await loadHome(page);
    expect(await scrollsSideways(page)).toBe(false);
    await expect(page.getByRole('heading', { name: 'NazareNow' })).toBeVisible();
    await expect(page.getByRole('navigation', { name: 'Pages' })).toBeVisible();

    await loadReading(page);
    expect(await scrollsSideways(page)).toBe(false);
    await expect(page.getByRole('navigation', { name: 'Pages' })).toBeVisible();
  });
});

/**
 * The slot the day list and one day's hours share (#118).
 *
 * This is the file that can prove it. The jsdom suite proves *what swaps* — that the list goes,
 * that the detail arrives, that focus follows — and cannot prove the one thing the ticket is
 * for, because jsdom gives every element a height of zero and "the column did not change
 * height" passes there against a column that doubles.
 */
test.describe(`the day slot, at ${DESKTOP.width}x${DESKTOP.height}`, () => {
  /** A day far enough down the list to be a real click rather than the first row. */
  const A_DAY = new RegExp(longForecast.days[3]!.date);

  test('leaves the column and the map exactly as they were when a day opens', async ({ page }) => {
    // The whole ticket, in one measurement. The detail used to render *beneath* the list, and
    // `.map-slot` is `height: 100%` of the column beside it — so opening a day lengthened the
    // column, restretched the map, and moved the page under the hands of the person who had
    // just clicked.
    const { left, slot } = await loadHome(page);

    const columnBefore = (await left.boundingBox())!;
    const mapBefore = (await slot.boundingBox())!;

    await page.getByRole('button', { name: A_DAY }).click();
    await expect(page.getByRole('table')).toBeVisible();

    const columnOpen = (await left.boundingBox())!;
    const mapOpen = (await slot.boundingBox())!;

    expect(columnOpen.height).toBeCloseTo(columnBefore.height, 1);
    // The proportion rather than the height, because the criterion is about the shape the map
    // is drawn into: a slot that grew in both directions would hold its aspect ratio and still
    // have moved everything below it.
    expect(mapOpen.height / mapOpen.width).toBeCloseTo(mapBefore.height / mapBefore.width, 3);
    expect(mapOpen.height).toBeCloseTo(mapBefore.height, 1);
  });

  test('puts the column and the map back exactly where they were on the way out', async ({
    page,
  }) => {
    // Opening and closing are two chances to move the page, and only one of them is the one
    // anybody thinks to measure. The map is measured on both for the same reason: a slot that
    // came back a few pixels short would restretch it on the way out rather than the way in,
    // which is the same defect arriving by the door nobody watched.
    const { left, slot } = await loadHome(page);
    const columnBefore = (await left.boundingBox())!;
    const mapBefore = (await slot.boundingBox())!;

    await page.getByRole('button', { name: A_DAY }).click();
    await expect(page.getByRole('table')).toBeVisible();
    await page.getByRole('button', { name: /back to all \d+ days/i }).click();
    await expect(page.getByRole('table')).toHaveCount(0);

    const mapAfter = (await slot.boundingBox())!;
    expect((await left.boundingBox())!.height).toBeCloseTo(columnBefore.height, 1);
    expect(mapAfter.height).toBeCloseTo(mapBefore.height, 1);
    expect(mapAfter.height / mapAfter.width).toBeCloseTo(mapBefore.height / mapBefore.width, 3);
  });

  test('keeps the keyboard cursor visible inside the slot it scrolls in', async ({ page }) => {
    // "What is focused is visible" is the half of the keyboard criterion that a test asserting
    // *where* focus went cannot reach. Two ways to fail it here, both introduced by putting the
    // rows in a scroller: a row focused while scrolled out of sight, and a focus ring clipped
    // by the box that is doing the scrolling.
    await loadHome(page);
    const deep = page.getByRole('button', { name: new RegExp(longForecast.days[14]!.date) });

    await deep.focus();

    const seen = await page.evaluate(() => {
      const box = document.querySelector('.column-scroll')!.getBoundingClientRect();
      const row = document.activeElement as HTMLElement;
      const rect = row.getBoundingClientRect();
      const style = getComputedStyle(row);
      // The ring is drawn outside the element: its width plus its offset is how much room it
      // needs on each side before the scroller's edge cuts it off.
      const ring = parseFloat(style.outlineWidth) + parseFloat(style.outlineOffset);
      return {
        isRow: row.classList.contains('day'),
        inView: rect.top >= box.top - 1 && rect.bottom <= box.bottom + 1,
        roomForRing: Math.min(rect.left - box.left, box.right - rect.right) >= ring,
      };
    });

    expect(seen.isRow).toBe(true);
    expect(seen.inView).toBe(true);
    expect(seen.roomForRing).toBe(true);
  });

  test('absorbs the day count into the scroller rather than into the page', async ({ page }) => {
    // The design spec's warning is that "any layout that assumes a fixed count is a layout that
    // breaks silently", so this is the assertion that the page has no opinion about the count.
    //
    // **Two halves, because either alone is worth nothing here.** Comparing the column's height
    // at three days and at sixteen is what this test did first, and it could not fail: the
    // column is pinned by the viewport whatever is inside it, so the assertion held even in the
    // broken state where the flex chain was severed and the tail grew to 1020 inside a column
    // of 818. What can fail is the page, and what proves the days are really there rather than
    // dropped is the scroller's content growing with them.
    await loadHome(page);
    const { height: viewportHeight } = await viewport(page);
    const sixteen = await page.evaluate(() => ({
      page: document.documentElement.scrollHeight,
      content: document.querySelector('.column-scroll')!.scrollHeight,
    }));

    // Added after the `beforeEach` stub, so it is matched first.
    await page.route('**/api/conditions/forecast', (route) =>
      route.fulfill({ json: { ...longForecast, days: longForecast.days.slice(0, 3) } }),
    );
    await loadHome(page);
    const three = await page.evaluate(() => ({
      page: document.documentElement.scrollHeight,
      content: document.querySelector('.column-scroll')!.scrollHeight,
    }));

    // The page fits at both counts, and measures the same at both.
    expect(sixteen.page).toBeLessThanOrEqual(viewportHeight);
    expect(three.page).toBeLessThanOrEqual(viewportHeight);
    expect(three.page).toBe(sixteen.page);

    // And the thirteen extra days went into the scroller, not into a page that grew or a list
    // that quietly shortened.
    expect(sixteen.content).toBeGreaterThan(three.content);
  });

  test('scrolls the column tail rather than lengthening the page', async ({ page }) => {
    // Sixteen rows and the limits under them do not fit below the fold, and are not meant to.
    // None is hidden, collapsed or trimmed — the days past the measured archive carry the most
    // Lead Time, and dropping them is what this layout exists not to do — so the overflow goes
    // inside a box whose height the page does not feel.
    //
    // **The scroller is the column's whole tail, not the day list.** #118 scrolled the list
    // alone, which left the calibration limit, the forecast provenance, the track-record line
    // and the footer outside the scroller and on the page — 393px of it — and no slot height
    // could close a gap those four were holding open.
    await loadHome(page);
    const tail = page.locator('.column-scroll');

    const overflow = await tail.evaluate((element) => element.scrollHeight - element.clientHeight);
    expect(overflow).toBeGreaterThan(0);
    expect(await tail.evaluate((element) => getComputedStyle(element).overflowY)).toBe('auto');

    // Every row is still in the document, scrolled rather than dropped.
    await expect(page.locator('.day')).toHaveCount(longForecast.days.length);

    // And every block that used to be stranded below it is inside it — named one by one,
    // because a loop over three of the four is a guard with a hole exactly where the fourth is.
    for (const inside of [
      '.day-slot',
      // Scoped to the scroller already, so these are bare: `.forecast .alert` would look for a
      // `.forecast` *inside* it, and the section is its ancestor.
      '.alert',
      '.provenance',
      '.track-record-line',
      'footer',
    ]) {
      await expect(tail.locator(inside)).toHaveCount(1);
    }
  });
});

test.describe('how tall the page is, which is the promise', () => {
  test('shows the verdict, the tiles and their provenance without scrolling', async ({ page }) => {
    // **The first half of the promise, and the half a page-height assertion cannot see.**
    // `.column-scroll` is a flex child, so anything added above the fold is paid for out of the
    // scroller before it is paid for out of the page: the block below could squeeze to a slit
    // while `scrollHeight` went on reporting exactly one viewport. That is the promise kept in
    // the letter and lost in the substance, so it is asserted directly.
    await loadHome(page);
    const { height: viewportHeight } = await viewport(page);

    const head = (await page.locator('.column-head').boundingBox())!;
    expect(head.y + head.height).toBeLessThanOrEqual(viewportHeight);

    // Each of the three the ruling names, by what a reader sees rather than by class.
    for (const block of [
      page.getByRole('heading', { level: 2 }).first(),
      page.getByTestId('tiles'),
      page.getByTestId('provenance'),
    ]) {
      const box = (await block.boundingBox())!;
      expect(box.y + box.height).toBeLessThanOrEqual(viewportHeight);
    }

    // And the scroller still has room to be a list rather than a slit.
    const tail = (await page.locator('.column-scroll').boundingBox())!;
    expect(tail.height).toBeGreaterThan(150);
  });

  test('fits a viewport at sixteen days, which is the no-scroll promise entire', async ({
    page,
  }) => {
    await loadHome(page);

    const { height: viewportHeight } = await viewport(page);
    const height = await page.evaluate(() => document.documentElement.scrollHeight);

    /**
     * **The promise, kept (#132).** This assertion was `toBeGreaterThan` from #115 until here:
     * a tripwire asserting the shortfall, written so that the ticket which closed the gap could
     * not close it quietly. This is that ticket.
     *
     * **Measured at 1440x900 against this fixture, never projected.** Every estimate written
     * into this docstring before #116 was wrong, and so were the ones on #132 — the sequence
     * there was 179 -> 478 -> 794 -> 776, and each wrong figure was an estimate of what a
     * ticket would remove that did not account for what the same ticket added.
     *
     * ```
     *                       #117   #128   #116   #119   #118   #132
     * page                  1945   1715   1642   1676   1430    900    viewport 900
     *   chrome               238     88     88     88     32     26
     *   .verdict               -      -    217    289    289    267
     *   .tiles                 -      -    123    123    123    123
     *   .conditions-provenance -      -     96     96     96     96
     *   ten condition cards  378    318      -      -      -      -
     *   .windows             171    171    171      -      -      -    <- moved by #119
     *   .days + divider      554    554    554    554      -      -    <- into the slot, #118
     *   .day-slot              -      -      -      -    416      *    <- * scrolls now
     *   .alert                74     74     74     98     98      *
     *   .forecast .provenance  -      -     48     48     48      *
     *   .track-record-line     -      -      -     98     98      *
     *   footer               107    107     59     41     41      *
     * ```
     *
     * `*` is the point. Everything marked with one is inside `.column-scroll`, so its height is
     * no longer the page's business at all — the page is a viewport, and the tail scrolls in
     * the space the fold leaves it.
     *
     * **What made the arithmetic close was widening the scroller, not finding 114px.** #118
     * scrolled the day list alone. That left the calibration limit, the forecast provenance,
     * the track-record line and the footer outside the scroller and on the page — 393px held
     * open by four blocks no slot height could reach. Of the ~190px of tightening sized on
     * #132, 128 was row padding, list gaps and divider margins, all of which #118 had moved
     * *inside* the slot: tightening them buys rows inside the scroller and moves the page not
     * at all. Only ~30 was ever outside it.
     *
     * The 22px this ticket does take out of the verdict is not what keeps the promise either.
     * The promise is kept by construction — `.page-forecast` is `height: 100vh` and the column
     * takes what the chrome leaves — and the 22px buys one more day row above the fold.
     *
     * **This is asserted at the count the fixture carries**, sixteen, not the eleven the
     * provider happens to send today: "any layout that assumes a fixed count is a layout that
     * breaks silently" is the design spec's own warning. And the page now measures the same at
     * three days as at sixteen, which `the day slot` above asserts directly — so this is a
     * property of the page rather than of the response, which is the stronger thing to hold.
     *
     * **Do not loosen this and do not delete it.** It is the whole promise, and the next thing
     * that pushes the page over a viewport should fail here rather than ship.
     */
    expect(height).toBeLessThanOrEqual(viewportHeight);
  });

  test('keeps the promise with a day open, not only with the list showing', async ({ page }) => {
    // The page has two states and the promise is about both. A page that fits until somebody
    // clicks something is not a page that fits.
    await loadHome(page);
    await page.getByRole('button', { name: new RegExp(longForecast.days[3]!.date) }).click();
    await expect(page.getByRole('table')).toBeVisible();

    const { height: viewportHeight } = await viewport(page);
    const height = await page.evaluate(() => document.documentElement.scrollHeight);

    expect(height).toBeLessThanOrEqual(viewportHeight);
  });
});
