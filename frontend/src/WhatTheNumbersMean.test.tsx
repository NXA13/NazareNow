/**
 * The section that says what every figure on this site is (#119).
 *
 * Pure copy, so there is no network and no fixture. What is worth guarding is not that the words
 * render — it is that the two claims they exist to make cannot be softened, and that the domain
 * vocabulary they depend on cannot drift into the synonyms `CONTEXT.md` forbids.
 *
 * The wording here is the one place on the site where the Face Height / Significant Wave Height
 * distinction is stated outright, and `CLAUDE.md` calls conflating them load-bearing: it
 * silently invalidates the model's evaluation. A reader who conflates them misjudges every
 * figure on the site by a factor nobody can state, because there is no fixed one.
 */

import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { HowItWorks } from './HowItWorks';
import { WhatTheNumbersMean } from './WhatTheNumbersMean';

describe('what the numbers are', () => {
  it('says every height is a significant wave height and not a wave face', async () => {
    render(<WhatTheNumbersMean />);

    const statement = screen.getByTestId('height-distinction');
    expect(statement).toHaveTextContent(/significant wave height/i);
    expect(statement).toHaveTextContent(/not the height of a wave face/i);
  });

  it('refuses the conversion a reader most wants, rather than omitting it', () => {
    // The dangerous kindness. A reader who knows the news figure will try to convert, and any
    // ratio offered here would be invented: CONTEXT.md says the two are "not convertible by any
    // fixed ratio". Saying nothing leaves them to invent their own, so the refusal is stated.
    render(<WhatTheNumbersMean />);

    const statement = screen.getByTestId('height-distinction');
    expect(statement).toHaveTextContent(/do not convert by any fixed ratio/i);
  });

  it('names the proxy target as a stand-in, and says where it is measured', () => {
    // The admission is the whole reason the concept has a name. A section that described the
    // mooring without saying it stands in for something else would read as the system being
    // trained on the right quantity.
    render(<WhatTheNumbersMean />);

    const proxy = screen.getByTestId('proxy-target');
    expect(proxy).toHaveTextContent(/proxy target/i);
    expect(proxy).toHaveTextContent(/15km offshore rather than at the beach/i);
    // Why a proxy is needed at all, which is the part that justifies it. CONTEXT.md says Face
    // Height has "no reliable historical archive", not that it cannot be looked up — the first
    // draft here said the stronger thing, which claims more than the glossary does.
    expect(proxy).toHaveTextContent(/no reliable historical archive/i);
  });

  it('says where the prediction stops, without claiming the system models nothing', () => {
    // The largest limit the system has, and it has to be stated without either softening
    // ("the model accounts for the canyon") or overshooting.
    //
    // **The first draft overshot.** It said the canyon's transformation was "exactly what this
    // system does not model", which contradicts CONTEXT.md — that transformation is
    // *Amplification*, "the relationship this system exists to learn" — and tells a reader the
    // product does nothing. The truth is narrower: it learns as far as the record reaches, and
    // the last stretch to the beach is unmodelled. Both halves are asserted, because either one
    // alone is the misleading version.
    render(<WhatTheNumbersMean />);

    const gap = screen.getByTestId('amplification-gap');
    expect(gap).toHaveTextContent(/the relationship this system exists to learn/i);
    expect(gap).toHaveTextContent(/from the mooring to the beach — is not modelled/i);
  });

  it('keeps the swell height apart from the combined figure', () => {
    // CONTEXT.md lists "swell height (a different variable)" under Significant Wave Height's
    // avoid list, and the forecast page renders both. A sentence claiming every height on the
    // site is a significant wave height would collapse the two it exists to separate.
    render(<WhatTheNumbersMean />);

    expect(screen.getByTestId('swell-height-aside')).toHaveTextContent(
      /travelled component on its own/i,
    );
  });

  it('lists all six conditions a Go Call has to clear', () => {
    // #119's move list names the six-gate chain. It was on neither page: it lived in the
    // backend's decision module, and the reading page's existing caveat named only the two of
    // the six that a reconstruction cannot ask.
    render(<WhatTheNumbersMean />);

    expect(screen.getAllByRole('listitem')).toHaveLength(6);
    expect(screen.getByTestId('gate-chain-intro')).toHaveTextContent(/six conditions/i);
  });

  it('says plainly that the threshold check does not cover these pages', () => {
    // The first draft claimed it did. `test_prose_marks_the_shipped_bars.py` names 21 files and
    // not one is a frontend file — so the claim was false, on the page describing the rule it
    // was false about. Stating the hole is the only honest version.
    render(<WhatTheNumbersMean />);

    expect(screen.getByTestId('current-numbers-rule')).toHaveTextContent(
      /does not yet cover these pages/i,
    );
  });

  it('uses none of the synonyms the glossary forbids for these concepts', () => {
    // `CONTEXT.md` gives each entry an `_Avoid_` list, and this section names the three entries
    // whose synonyms do the most damage. "Ground truth" and "target variable" would claim the
    // proxy is the answer; "wave size" and a bare "wave height" collapse the distinction the
    // section exists to draw. ADR 0014 is the rule that avoid-lists forbid naming the thing.
    const { container } = render(<WhatTheNumbersMean />);
    const copy = container.textContent ?? '';

    for (const forbidden of [
      'ground truth',
      'target variable',
      'wave size',
      'epic',
      'big day',
      // Amplification's own avoid list. The first draft wrote "the canyon focuses swell",
      // which names the thing ADR 0014 says an avoid list forbids naming.
      'focus',
      'magnification',
      'canyon effect',
    ]) {
      expect(copy.toLowerCase(), `copy uses "${forbidden}"`).not.toContain(forbidden);
    }
  });

  it('comes before the record it governs, not after it', () => {
    // A footnote under the numbers is read second, and by then every height on the page has
    // already been read as something several times larger than it is.
    render(<HowItWorks />);

    const distinction = screen.getByTestId('height-distinction');
    const record = screen.getByRole('heading', { name: /track record/i });

    expect(distinction.compareDocumentPosition(record)).toBe(Node.DOCUMENT_POSITION_FOLLOWING);
  });
});
