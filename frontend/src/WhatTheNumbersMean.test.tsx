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
    // Why a proxy is needed at all, which is the part that justifies it.
    expect(proxy).toHaveTextContent(/cannot be looked up historically/i);
  });

  it('says the canyon transformation is the thing not modelled', () => {
    // The largest limit the system has, and the one most likely to be softened into "the model
    // accounts for the canyon" by anyone editing for confidence.
    render(<WhatTheNumbersMean />);

    expect(screen.getByTestId('amplification-gap')).toHaveTextContent(
      /exactly what this system does not model/i,
    );
  });

  it('uses none of the synonyms the glossary forbids for these concepts', () => {
    // `CONTEXT.md` gives each entry an `_Avoid_` list, and this section names the three entries
    // whose synonyms do the most damage. "Ground truth" and "target variable" would claim the
    // proxy is the answer; "wave size" and a bare "wave height" collapse the distinction the
    // section exists to draw. ADR 0014 is the rule that avoid-lists forbid naming the thing.
    const { container } = render(<WhatTheNumbersMean />);
    const copy = container.textContent ?? '';

    for (const forbidden of ['ground truth', 'target variable', 'wave size', 'epic', 'big day']) {
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
