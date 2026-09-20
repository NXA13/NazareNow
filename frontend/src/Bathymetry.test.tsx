/**
 * The sea floor, held to the four defects the prototype already found (#121).
 *
 * `prototypes/v2-map/README.md` lists them, and the ticket's requirement is that none reappears
 * and that the tests say so **by name**. Each one looks like a styling problem and is not: three
 * of the four render as something plausible rather than as something broken, which is why they
 * survived a look at the screen and needed a list.
 *
 * jsdom does no layout, so nothing here measures anything. What it can see is the markup — the
 * order paths are painted in, the fill rule each carries, and where a path closes — and all four
 * defects live in exactly those.
 */

import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';

import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { Bathymetry } from './Bathymetry';
import geometry from './map-geometry.json';
import packageJson from '../package.json';

/** The map, as the element a reader is offered rather than as a container. */
function draw() {
  render(<Bathymetry />);
  return screen.getByRole('img', { name: /sea floor|canyon/i });
}

describe('the sea floor comes from soundings', () => {
  it('draws the geometry the build step produced, not a shape written here', () => {
    // The guard against the defect the ticket exists to prevent: a hand-drawn canyon. Every
    // path on this map has to be one the tracer emitted.
    const map = draw();
    const emitted = new Set(Object.values(geometry.levels as Record<string, string[]>).flat());

    const drawn = [...map.querySelectorAll('.bathymetry-hairline')].map((p) => p.getAttribute('d'));
    expect(drawn.length).toBeGreaterThan(0);
    for (const path of drawn) {
      // Each hairline is the level's traced paths concatenated, so every piece of it is the
      // tracer's own output.
      expect([...emitted].some((candidate) => path!.includes(candidate))).toBe(true);
    }
  });

  it('covers the depth range with more than a token contour or two', () => {
    // A map that rendered one level would satisfy every structural assertion below while
    // showing none of the canyon.
    expect(draw().querySelectorAll('.bathymetry-band')).toHaveLength(8);
  });
});

describe('the four defects the prototype already found', () => {
  it('1. paints the bands shallow to deep, or the shelf tone floods the whole ocean', () => {
    // Each level's path fills everything *deeper* than it. Painted deep-to-shallow the
    // shallowest level covers everything and the canyon disappears completely — a blank grey
    // panel that reads as a rendering failure rather than as a wrong order.
    const order = [...draw().querySelectorAll('.bathymetry-band')].map((path) =>
      // `getAttribute`, not `className`: on an SVG element that property is an
      // `SVGAnimatedString` rather than a string, and `querySelectorAll` types it as neither.
      Number(path.getAttribute('class')!.match(/bathymetry-band-(\d+)/)![1]),
    );

    expect(order).toEqual([0, 1, 2, 3, 4, 5, 6, 7]);
  });

  it('2. fills every band even-odd, so a seamount is a rise and not a blob', () => {
    // A closed loop inside a band is a rise — a seamount, or the shoulder between the canyon
    // and the shelf. Under the default non-zero rule it paints as a dark blob in open water.
    // Two of those appeared in the prototype and were mistaken for land.
    const map = draw();

    for (const band of map.querySelectorAll('.bathymetry-band')) {
      expect(band.getAttribute('fill-rule')).toBe('evenodd');
    }
    // The land carries it too, which is what makes the Lagoa de Óbidos a lagoon punched back
    // out of the land rather than an inlet painted over.
    expect(map.querySelector('.bathymetry-land')!.getAttribute('fill-rule')).toBe('evenodd');
  });

  it('3. closes the coast around the frame edge, not end-to-start, so no teardrop sits at sea', () => {
    // Closing an open coast segment straight from its last point back to its first draws a
    // teardrop out in open water, which is what the prototype's first render did. It is closed
    // around the eastern edge instead — so the path must reach beyond the frame's own width.
    const map = draw();
    const land = map.querySelector('.bathymetry-land')!.getAttribute('d')!;
    const width = Number(geometry.viewBox.split(' ')[2]);
    const xs = [...land.matchAll(/[ML](-?[\d.]+),/g)].map((match) => Number(match[1]));

    expect(land.endsWith('Z')).toBe(true);
    expect(Math.max(...xs)).toBeGreaterThan(width);

    // **And the bands close by walking the frame, which is the same defect one level up.**
    // Closing every open contour westward was the first attempt here and it is wrong for two of
    // the eight: at −20 the contour enters on the east edge and leaves on the south, so a
    // straight westward closure cuts a chord across the frame and drops the whole top strip out
    // of the band. A band is "everything deeper than this level", and deep water is west across
    // this frame, so the closure has to go round the western side — through three corners.
    const height = Number(geometry.viewBox.split(' ')[3]);
    const shallowest = map.querySelector('.bathymetry-band-0')!.getAttribute('d')!;

    for (const corner of [`0.0,${height.toFixed(1)}`, '0.0,0.0', `${width.toFixed(1)},0.0`]) {
      expect(shallowest, `the shallowest band does not reach ${corner}`).toContain(corner);
    }
  });

  it('4. carries no wind glyph yet, so the one that flies tail-first cannot be here', () => {
    // The fourth defect is a rotation: a glyph drawn with its apex at −y flies tail-first, at
    // the correct speed and in the correct direction, which is what makes it hard to spot.
    // Wind is #123 and nothing on this map rotates, so the guard here is that there is nothing
    // for the defect to be in. #123 replaces this with the real assertion.
    const map = draw();

    expect(map.querySelectorAll('[transform]')).toHaveLength(0);
    expect(map.querySelectorAll('animate, animateTransform')).toHaveLength(0);
  });
});

describe('what the base map is allowed to be', () => {
  const read = (relative: string) =>
    readFileSync(fileURLToPath(new URL(relative, import.meta.url)), 'utf8');

  it('carries no colour of its own, because on this map colour means live data', () => {
    /*
     * Two halves, and the review found the second one missing.
     *
     * `ink.test.ts` forbids a colour *literal* outside `tokens.css` — it does not check that
     * anything in `tokens.css` is grey. So the map's tones could have been made blue and every
     * test would have passed, while the one rule this base map has is that colour on it means
     * live data and the sea floor is not live data.
     *
     * The first half is here: no fill or stroke written into the markup, where that guard
     * cannot see it. The second is below: every map token is a true grey.
     */
    const map = draw();

    for (const node of map.querySelectorAll('*')) {
      for (const attribute of ['fill', 'stroke', 'style']) {
        const value = node.getAttribute(attribute);
        if (value === null || value === 'none') continue;
        expect(value, `${node.nodeName} sets ${attribute}="${value}"`).toMatch(/^var\(--/);
      }
    }
  });

  it('draws every tone in a true grey, so nothing on the base map can read as data', () => {
    const tokens = read('./tokens.css');
    const greys = [...tokens.matchAll(/(--map-[a-z0-9-]+):\s*#([0-9a-f]{6})/g)];

    // All of them, by count: a regex that matched nothing would pass every assertion below.
    expect(greys.length).toBeGreaterThanOrEqual(10);

    for (const [, name, hex] of greys) {
      const [r, g, b] = [0, 2, 4].map((i) => parseInt(hex!.slice(i, i + 2), 16));
      expect([name, r, g, b].join(' '), `${name} is not a grey`).toBe([name, r, r, r].join(' '));
    }
  });

  it('adds no map library and no charting library', () => {
    // Inline SVG, per the ticket. The frame is one fixed view of one fixed place and nothing
    // reprojects anything, so there is nothing for a library to do — and a map library would
    // cost more than the whole payload budget.
    const dependencies = Object.keys({
      ...packageJson.dependencies,
      ...packageJson.devDependencies,
    });

    for (const banned of ['leaflet', 'mapbox', 'maplibre', 'openlayers', 'd3', 'chart.js']) {
      expect(dependencies.filter((name) => name.includes(banned))).toEqual([]);
    }
  });

  it('never calls the canyon by a name CONTEXT.md forbids', () => {
    /*
     * ADR 0014: an avoid list forbids naming the thing. The review of this very ticket found it
     * broken — "the trench" twice, once in a component comment and once in a token note — which
     * is the second time a list has been broken silently in this repository.
     *
     * **The sweep reads source text, not rendered copy**, because that is where it happened and
     * because a comment naming the canyon wrongly teaches the next person to name it wrongly.
     * The terms are parsed out of `CONTEXT.md` rather than copied here, so the guard cannot
     * drift from the list it enforces.
     */
    const read = (relative: string) =>
      readFileSync(fileURLToPath(new URL(relative, import.meta.url)), 'utf8');

    const context = read('../../CONTEXT.md');
    const entry = context.match(/\*\*Nazaré Canyon\*\*:[\s\S]*?_Avoid_: (.+)/)!;
    const forbidden = entry[1]!.split(',').map((term) => term.trim().toLowerCase());
    expect(forbidden).toContain('the trench');

    const sources = ['./Bathymetry.tsx', './MapSlot.tsx', './tokens.css', './App.css'];
    for (const source of sources) {
      const text = read(source).toLowerCase();
      for (const term of forbidden) {
        expect(text, `${source} names the canyon as "${term}"`).not.toContain(term);
      }
    }
  });

  it('tells a reader it is depth rather than today, under the figure', () => {
    // ADR 0012's rule is that prose says whether a number is current. A picture owes the same,
    // and this one is not current at all — it is permanent. A reader taking a feature of the
    // sea bed for a forecast is this project's characteristic failure.
    expect(draw()).toHaveAttribute('aria-label', expect.stringMatching(/sea floor/i));
  });
});
