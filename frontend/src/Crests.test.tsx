/**
 * The crests, as a reader gets them.
 *
 * `refraction.test.ts` proves the physics and `refraction.parity.test.ts` proves the port.
 * What is left for this file is the part those cannot see: that the page draws nothing at all
 * before the conditions arrive, that it draws both halves of every front when they do, and
 * that a change in the sea changes the picture rather than a cached one being redrawn.
 */

import { render } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { Crests } from './Crests';

/** The crests live inside the map's SVG, so they need one to be rendered into. */
function draw(swell: Parameters<typeof Crests>[0]['swell']) {
  const { container } = render(
    <svg viewBox="0 0 686.8 780">
      <Crests swell={swell} />
    </svg>,
  );
  return container;
}

const GOLD_DAY = { periodSeconds: 13.75, fromDirectionDeg: 310 };

describe('Crests', () => {
  it('draws nothing at all before the conditions arrive', () => {
    // The map's column exists in every state, including before the conditions load and after
    // they fail. A crest drawn from a default swell would be a picture of a sea nobody
    // reported — the characteristic failure this project guards against.
    expect(draw(null).querySelectorAll('path')).toHaveLength(0);
  });

  it('draws the front dim in deep water and bright inside the shoaling zone', () => {
    const container = draw(GOLD_DAY);
    const deep = container.querySelectorAll('.bathymetry-crest-deep');
    const shoaling = container.querySelectorAll('.bathymetry-crest-shoaling');
    expect(deep.length).toBeGreaterThan(0);
    expect(shoaling.length).toBeGreaterThan(0);
  });

  it('gives every crest a class rather than a colour of its own', () => {
    // `ink.test.ts` forbids colour literals outside `tokens.css`, but it reads stylesheets —
    // a `stroke` attribute set here would sail past it.
    for (const path of draw(GOLD_DAY).querySelectorAll('path')) {
      expect(path.getAttribute('stroke')).toBeNull();
      expect(path.getAttribute('style')).toBeNull();
      expect(path.getAttribute('class')).toMatch(/bathymetry-crest/);
    }
  });

  it('draws a different sea when the swell changes', () => {
    // Without this, a solve that ignored its arguments and returned one cached field would
    // pass every other test here.
    const northerly = [
      ...draw({ periodSeconds: 13.75, fromDirectionDeg: 0 }).querySelectorAll('path'),
    ]
      .map((p) => p.getAttribute('d'))
      .join('');
    const westerly = [
      ...draw({ periodSeconds: 13.75, fromDirectionDeg: 270 }).querySelectorAll('path'),
    ]
      .map((p) => p.getAttribute('d'))
      .join('');
    expect(northerly.length).toBeGreaterThan(0);
    expect(westerly).not.toBe(northerly);
  });

  it('draws a different sea when only the period changes', () => {
    const long = [...draw({ periodSeconds: 16, fromDirectionDeg: 310 }).querySelectorAll('path')]
      .map((p) => p.getAttribute('d'))
      .join('');
    const short = [...draw({ periodSeconds: 8, fromDirectionDeg: 310 }).querySelectorAll('path')]
      .map((p) => p.getAttribute('d'))
      .join('');
    expect(long.length).toBeGreaterThan(0);
    expect(short).not.toBe(long);
  });
});
