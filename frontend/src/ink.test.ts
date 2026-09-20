/**
 * The Ink visual system, held to its own rules (#114).
 *
 * Every acceptance criterion that ticket carries about colour, type and payload is a rule a
 * later change can break silently and invisibly: a component that reaches for a hex value
 * because the token was one keystroke further away, a number that ends up in the text face
 * because it was interpolated into a sentence, a font that goes back to a CDN because that is
 * one line shorter than committing a file. None of those break a rendering test, and none of
 * them look wrong in a screenshot taken by the person who made the change.
 *
 * So they are asserted here, against the stylesheets as text. This is the same shape as
 * `every-field-is-read.test.tsx`: a rule about the whole surface, enforced once, rather than a
 * habit each new component is trusted to keep.
 *
 * What is *not* here: whether the re-skin looks good. That is Nick's call on the running app,
 * and no test can hold it.
 */

import { readFileSync, readdirSync, statSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';

import { contrastRatio, measure, parseColour, parseTokens } from '../scripts/check-contrast.mjs';
import { REPERTOIRE } from '../scripts/fetch-fonts.mjs';

// Through `fileURLToPath` rather than the URL's own `pathname`, which on Windows hands back
// `/C:/...` — the trap `check-payload.mjs` documents.
const here = (relative: string) => fileURLToPath(new URL(relative, import.meta.url));

const read = (relative: string) => readFileSync(here(relative), 'utf8');

const TOKENS = read('./tokens.css');
const APP = read('./App.css');
const INDEX = read('../index.html');

/** The sheets and components a rule about "no component names a value" applies to: everything
 * the browser is served except the one file where the values are decided. */
const SHIPPED_SOURCE = readdirSync(here('.'))
  .filter((name) => /\.(css|tsx?)$/.test(name))
  .filter((name) => !name.endsWith('.test.ts') && !name.endsWith('.test.tsx'))
  .filter((name) => name !== 'tokens.css')
  .map((name) => ({ name, text: read(`./${name}`) }));

/** CSS comments and `//` comments carry prose about colours; the rules are what is asserted. */
function withoutComments(source: string): string {
  return source.replace(/\/\*[\s\S]*?\*\//g, '').replace(/^\s*\/\/.*$/gm, '');
}

/** Each `selector { body }` pair in a sheet, comments already stripped. */
function rules(css: string): { selector: string; body: string }[] {
  return [...withoutComments(css).matchAll(/([^{}]+)\{([^{}]*)\}/g)].map((match) => ({
    selector: match[1]!.trim().replace(/\s+/g, ' '),
    body: match[2]!.trim(),
  }));
}

describe('every colour, font and size lives in one place', () => {
  it('names no colour outside the tokens sheet', () => {
    const offenders = SHIPPED_SOURCE.flatMap(({ name, text }) =>
      [...withoutComments(text).matchAll(/#[0-9a-f]{3,8}\b|\brgba?\(/gi)].map(
        (match) => `${name}: ${match[0]}`,
      ),
    );

    expect(offenders).toEqual([]);
  });

  it('names no face and no size outside the tokens sheet', () => {
    // `font:` shorthand included, because `font: inherit` is legitimate and `font: 12px/1.4
    // Helvetica` would smuggle both past a check that only looked for the longhands.
    const declarations = [
      ...withoutComments(APP).matchAll(/\bfont(-family|-size)?\s*:\s*([^;]+)/g),
    ];

    const offenders = declarations
      .map((match) => ({ property: `font${match[1] ?? ''}`, value: match[2]!.trim() }))
      .filter(({ value }) => !value.includes('var(--') && value !== 'inherit');

    expect(offenders).toEqual([]);
  });

  it('defines the three colour systems as separate tokens', () => {
    for (const token of ['--ink-go', '--ink-watch', '--ink-main', '--ink-wind']) {
      expect(TOKENS).toContain(`${token}:`);
    }
  });
});

describe('the three colour systems stay apart', () => {
  /**
   * The whole of Ice's licence: the wordmark, the nav, links — and, since #122, the swell.
   *
   * The crests are not an exception grudgingly made. `tokens.css` has said since #114 that Main
   * carries "the swell crests when the map arrives", and the base map is greyscale precisely so
   * that colour on it can mean live data. What this list still forbids is the thing that would
   * actually hurt: Ice on the verdict panel or a call badge, where the brand would compete with
   * the call for attention.
   */
  const ICE_BELONGS_TO = [
    'header h1',
    'header nav a',
    'a',
    '.bathymetry-crest-deep',
    '.bathymetry-crest-shoaling',
  ];

  it('puts Ice on the wordmark, the nav, links and the swell, and nowhere else', () => {
    const misuse = rules(APP)
      .filter((rule) => rule.body.includes('var(--ink-main)'))
      .map((rule) => rule.selector)
      .filter((selector) => !ICE_BELONGS_TO.includes(selector));

    expect(misuse).toEqual([]);
  });

  it('gives every call badge a status colour and never the main colour', () => {
    const badges = rules(APP).filter((rule) => /^\.call-(go|confirmed|watch)$/.test(rule.selector));

    // All three, or a status was dropped and this test would otherwise pass on the rest.
    expect(badges.map((rule) => rule.selector).sort()).toEqual([
      '.call-confirmed',
      '.call-go',
      '.call-watch',
    ]);

    for (const badge of badges) {
      expect(badge.body).toMatch(/var\(--ink-(go|watch)(-dim)?\)/);
      expect(badge.body).not.toContain('var(--ink-main)');
    }
  });

  it('keeps status colour off the comparison bars, selection and model performance', () => {
    // How one height compares with the tallest beside it is not a judgement about travelling.
    // The two sharing a colour is the confusion this page exists to prevent.
    //
    // **`.track` and `.fill` are named here because they replaced what was.** This arm used to
    // read `^\.day\.rank-`, for the three classes that ranked a day against its week. #117 drew
    // that comparison as a bar instead and deleted them — and because four other selectors still
    // matched, the arm went on passing while guarding nothing. A rule that was a test would have
    // become a comment in `App.css` asking to be kept by hand.
    const notStatus = rules(APP).filter((rule) =>
      /^\.track$|^\.fill$|^\.day\.day\.selected$|^\.better$|^\.worse$|^:focus-visible$/.test(
        rule.selector,
      ),
    );

    // Every one of them, by name. `toBeGreaterThan(0)` is what let the rank arm empty out
    // unnoticed, because the other selectors kept the count above zero on their own.
    expect(notStatus.map((rule) => rule.selector).sort()).toEqual([
      '.better',
      '.day.day.selected',
      '.fill',
      '.track',
      '.worse',
      ':focus-visible',
    ]);
    for (const rule of notStatus) {
      expect(rule.body).not.toMatch(/var\(--ink-(go|watch)(-dim)?\)/);
    }
  });
});

describe('a limit is never set quieter than the figure it qualifies', () => {
  /**
   * #116's acceptance criterion, as a rule rather than a promise: "the modelled-not-measured
   * provenance and the height-only caveat on the probability are no smaller, dimmer or later
   * than the figures they qualify".
   *
   * This is the project's characteristic failure and it is a styling failure, not a copy one.
   * The caveat can be present, accurate and well worded, and still be defeated by one step down
   * the type scale and one step toward the muted tone — which is what a redesign does to a
   * disclaimer without anyone deciding to. So it is checked in the sheet.
   *
   * **Every rule that reaches the selector, not the one rule that spells it.** The first version
   * of this block looked up an exact selector string with `find`, which inspected one rule and
   * ignored the cascade: a later `.verdict-go .verdict-scope { color: var(--ink-muted) }`, or a
   * second `.verdict-scope` block further down the sheet, passed it untouched. It also said
   * nothing about `opacity`, which dims text without naming a colour at all.
   */
  const LIMITS = [
    '.verdict-scope',
    '.conditions-provenance',
    // Added by #119: the height-only caveat inside the day panel, which was muted and a size
    // down while the verdict's copy of the same sentence was correct. The review found it
    // because this guard did not.
    '.plausible-range-scope',
  ];

  // `.range-admission` is deliberately absent. It has no rule of its own — it takes its size and
  // tone from `.verdict-scope`, which is on this list — and adding it here would trip the arm
  // below that requires every named class to be styled, forcing a no-op rule into the sheet to
  // satisfy a test. What keeps it covered is that it carries `verdict-scope` in the markup, and
  // `App.test.tsx` asserts that rather than leaving it to be noticed.

  /** Every rule in the sheet whose selector could apply to this class, including descendant and
   * compound forms. A bare `includes` on purpose: it over-matches rather than under-matches, and
   * a guard that errs toward catching too much is the right error for this one to make. */
  const reaching = (klass: string) => rules(APP).filter((rule) => rule.selector.includes(klass));

  it.each(LIMITS)('has %s in the sheet at all', (klass) => {
    // Without this the two arms below pass vacuously against a class nobody styles, which is
    // what they would do the day someone renames it.
    expect(reaching(klass).length).toBeGreaterThan(0);
  });

  it.each(LIMITS)('never sets %s in the muted tone, in any rule that reaches it', (klass) => {
    for (const rule of reaching(klass)) {
      expect(rule.body, `${rule.selector} dims the limit`).not.toContain('var(--ink-muted)');
    }
  });

  it.each(LIMITS)('never fades %s with opacity or a filter', (klass) => {
    // The way a disclaimer gets quieter without anyone writing a colour down.
    for (const rule of reaching(klass)) {
      expect(rule.body, `${rule.selector} fades the limit`).not.toMatch(
        /\bopacity\s*:|\bfilter\s*:/,
      );
    }
  });

  it('sets the caveat in the same bright tone as the figures it sits under', () => {
    const scope = reaching('.verdict-scope')
      .map((rule) => rule.body)
      .join('\n');
    expect(scope).toContain('var(--ink-text)');
  });

  it('keeps the caveat and the prose on one shared size, so neither can shrink alone', () => {
    // `.verdict-detail` and `.verdict-scope` share a single `font-size` declaration, so there is
    // no state in which the caveat is smaller than the sentence it follows. What this catches is
    // that rule being split — after which the two can drift a step apart at any time.
    const shared = rules(APP).find((rule) => rule.selector === '.verdict-detail, .verdict-scope');
    expect(shared?.body, 'the shared size rule has been split').toMatch(
      /font-size:\s*var\(--text-/,
    );

    for (const rule of [...reaching('.verdict-scope'), ...reaching('.verdict-detail')]) {
      if (rule.selector === '.verdict-detail, .verdict-scope') continue;
      expect(rule.body, `${rule.selector} sets its own size`).not.toContain('font-size');
    }
  });
});

describe('every number is set in IBM Plex Mono', () => {
  it('serves digits from the mono face even inside a sentence', () => {
    // The structural half of the criterion: `format.ts` returns strings that land in the middle
    // of prose, so the text stack itself has to lead with a mono face scoped to digits.
    const textStack = TOKENS.match(/--font-text:\s*([^;]+);/)?.[1] ?? '';
    expect(textStack.trim().startsWith("'Plex Digits'")).toBe(true);

    const digitFaces = [...TOKENS.matchAll(/@font-face\s*\{([^}]*'Plex Digits'[^}]*)\}/g)].map(
      (match) => match[1]!,
    );

    // One for the regular weight and one for bold, so a number inside a `<strong>` is a bold
    // mono number rather than a synthesised one.
    expect(digitFaces).toHaveLength(2);
    for (const face of digitFaces) {
      expect(face).toContain('U+30-39');
      expect(face).toMatch(/ibm-plex-mono-\d+\.woff2/);
    }
  });

  it('sets the tables, the figures and the ladder in the full mono face', () => {
    // Anything that is all figures asks for the face by name; these are the selectors where a
    // number would otherwise be left in the text face at a size where it is read as data.
    const mono = ['.value', '.unit', '.bearing', '.figure', '.tier dd', '.history .range'];
    for (const selector of mono) {
      const rule = rules(APP).find((candidate) => candidate.selector === selector);
      expect(rule?.body, `${selector} should set the mono face`).toContain(
        'font-family: var(--font-mono)',
      );
    }

    for (const table of ['.hours-scroll table', '.record-table table']) {
      const rule = rules(APP).find((candidate) => candidate.selector === table);
      expect(rule?.body, `${table} should set the mono face`).toContain(
        'font-family: var(--font-mono)',
      );
    }
  });
});

describe('a figure that lands in prose is wrapped', () => {
  /**
   * A figure interpolated into JSX — `{metres(x)}` — and deliberately not one interpolated into
   * a template literal, which is `${metres(x)}` and matches nothing here.
   *
   * That single character is the whole distinction between markup and string-building, and it is
   * what keeps this guard honest. A figure inside a template literal is either an `aria-label`,
   * which a screen reader is read and a browser never draws, so it has no face to get wrong; or
   * it is a helper like `spreadRange` returning a string, in which case the face is decided
   * where that string lands in JSX, and this guard checks it there instead.
   */
  const FIGURE_IN_JSX = /(?<!\$)\{(formatValue|formatReading|formatRange|metres|signedMetres)\(/g;

  /** Contexts already mono by selector, so a figure inside one needs no wrapper. */
  const ALREADY_MONO = /<Figure>|<td|<dd>|className="value"|className="bearing"|className="range"/;

  it.each(['Forecast.tsx', 'TrackRecord.tsx'])(
    'sets every figure in %s in the mono face, by selector or by wrapper',
    (name) => {
      const source = withoutComments(read(`./${name}`));
      const bare: string[] = [];

      for (const match of source.matchAll(FIGURE_IN_JSX)) {
        // The window either side is generous because JSX puts the opening tag on its own line as
        // often as not. This is a guard against a figure landing in prose with nothing around
        // it, not a parser.
        const context = source.slice(Math.max(0, match.index - 220), match.index + 160);
        if (!ALREADY_MONO.test(context)) {
          bare.push(source.slice(Math.max(0, match.index - 70), match.index + 70).trim());
        }
      }

      expect(bare).toEqual([]);
    },
  );
});

describe('both fonts are served from this origin', () => {
  it('fetches no font from a third party', () => {
    for (const [name, text] of [
      ['tokens.css', TOKENS],
      ['App.css', APP],
      ['index.html', INDEX],
    ] as const) {
      expect(text, `${name} should not reach for a font CDN`).not.toMatch(
        /fonts\.googleapis\.com|fonts\.gstatic\.com|use\.typekit|cdn\.jsdelivr|unpkg\.com/,
      );
    }

    // Every `src` in the sheet is a relative path into this project.
    const sources = [...TOKENS.matchAll(/src:\s*url\('([^']+)'\)/g)].map((match) => match[1]!);
    expect(sources.length).toBeGreaterThan(0);
    for (const source of sources) {
      expect(source.startsWith('./fonts/')).toBe(true);
    }
  });

  it('carries the subset files it names, and no others', () => {
    const named = [...TOKENS.matchAll(/url\('\.\/fonts\/([^']+)'\)/g)].map((match) => match[1]!);
    const present = readdirSync(here('./fonts'));

    expect([...new Set(named)].sort()).toEqual(present.sort());

    // A ceiling, not a target: a refetch that lost the `text=` parameter would come back with
    // the whole family — about ten times this — and still work locally.
    for (const file of present) {
      const kb = statSync(here(`./fonts/${file}`)).size / 1024;
      expect(kb, `${file} is ${kb.toFixed(1)} kB, which is not a subset`).toBeLessThan(30);
    }
  });

  it('subsets to glyphs that cover everything either page renders', () => {
    const uncovered = new Map<string, string[]>();

    for (const { name, text } of [...SHIPPED_SOURCE, { name: 'index.html', text: INDEX }]) {
      for (const character of new Set(withoutComments(text).replace(/\s/g, ''))) {
        if (!REPERTOIRE.includes(character)) {
          uncovered.set(character, [...(uncovered.get(character) ?? []), name]);
        }
      }
    }

    // A character the source renders and the subset does not carry falls back to a system face
    // mid-sentence. `scripts/fetch-fonts.mjs` holds the repertoire and the one known gap.
    expect(Object.fromEntries(uncovered)).toEqual({});
  });

  it('carries every letter in both cases, because the sheet uppercases at paint time (#130)', () => {
    /*
     * **The test above reads the source; the browser reads the source *transformed*.**
     *
     * `text-transform: uppercase` is applied at paint, so a rule that uppercases an element
     * renders characters that appear nowhere in the source the guard above sweeps. The hour
     * table is where it showed: the caption and the `Time (Nazaré)` header are both uppercased,
     * the source says `é` and is covered, and what a reader actually got was NAZAR, one
     * system-face É, mid-word, in the first column of the panel they had just opened.
     *
     * So the rule is about the repertoire rather than about the sheet: **every letter carried is
     * carried in both cases.** The alternative was to teach the guard to find the sheet's
     * uppercasing selectors and fold them in, which is a second thing to keep in step with
     * `App.css` — and the failure it guards against is precisely the one nobody notices. This
     * cannot rot: a new `text-transform: uppercase` on any rule cannot introduce a fallback
     * glyph, because there is no letter here whose uppercase is missing.
     *
     * Cheap, too. The accented letters are nine, the list is deliberately short, and the cost is
     * nine glyphs across two faces.
     */
    // Named as the glyph that is *missing*, not as the lowercase that implies it: "É is not
    // carried" is the sentence somebody can act on.
    const missing = [...new Set(REPERTOIRE)]
      .map((character) => character.toUpperCase())
      .filter((upper) => !REPERTOIRE.includes(upper));

    expect(missing).toEqual([]);
  });
});

describe('contrast is measured against the ground, not assumed', () => {
  const measured = measure(TOKENS);

  it('measures every foreground the sheet puts on a ground', () => {
    // The pairs are declared in the script; this is the guard against a token being added to
    // the sheet and quietly never measured.
    const colours = [...TOKENS.matchAll(/(--ink-[a-z-]+):/g)].map((match) => match[1]!);
    const paired = new Set(measured.flatMap((row) => [row.fore, row.back]));

    expect(colours.filter((token) => !paired.has(token))).toEqual([]);
  });

  it.each(measured.filter((row) => row.gate !== null))(
    '$fore on $back clears $gate:1',
    ({ fore, back, gate, ratio }) => {
      expect(ratio, `${fore} on ${back} is ${ratio.toFixed(2)}:1`).toBeGreaterThanOrEqual(gate!);
    },
  );

  it('has the contract its declaration file claims it has', () => {
    // `scripts/` is outside tsconfig's `include`, so `tsc` never reads the `.mjs` and cannot
    // compare it with the `.d.mts` beside it. That is ADR 0013's hazard — two names for one
    // thing across a file boundary, with nothing checking them — so the check is here instead.
    // A field renamed or a return type changed in the script fails this rather than
    // type-checking cleanly against a description that has stopped being true.
    expect(typeof parseTokens).toBe('function');
    expect(typeof parseColour).toBe('function');
    expect(typeof contrastRatio).toBe('function');
    expect(typeof measure).toBe('function');

    expect(parseTokens('--a: #fff;').get('--a')).toBe('#fff');
    expect(parseColour('#8ecfe6')).toEqual({ channels: [142, 207, 230], alpha: 1 });
    expect(parseColour('rgba(206, 202, 194, 0.85)')).toEqual({
      channels: [206, 202, 194],
      alpha: 0.85,
    });

    // White on black is the one ratio in WCAG with a known exact value, so it checks the
    // arithmetic rather than only the plumbing.
    const ratio = contrastRatio(
      { channels: [255, 255, 255], alpha: 1 },
      { channels: [0, 0, 0], alpha: 1 },
    );
    expect(ratio).toBeCloseTo(21, 5);

    for (const row of measured) {
      expect(Object.keys(row).sort()).toEqual(
        ['back', 'fore', 'gate', 'passes', 'ratio', 'why'].sort(),
      );
      expect(typeof row.fore).toBe('string');
      expect(typeof row.back).toBe('string');
      expect(typeof row.ratio).toBe('number');
      expect(typeof row.passes).toBe('boolean');
      expect(typeof row.why).toBe('string');
      expect(row.gate === null || typeof row.gate === 'number').toBe(true);
    }
  });

  it('reports the pastels as clearing AA on the graphite ground', () => {
    // The claim the prototype's palette comment makes — "light enough to clear 4.5:1 on this
    // ground at small sizes" — now measured rather than believed.
    const statuses = measured.filter(
      (row) => /--ink-(go|watch)$/.test(row.fore) && row.back === '--ink-page',
    );

    expect(statuses).toHaveLength(2);
    for (const status of statuses) {
      expect(status.ratio).toBeGreaterThan(4.5);
    }
  });
});
