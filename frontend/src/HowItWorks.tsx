/**
 * The second page: how the site decides, and how well it has done.
 *
 * Today it carries the track record and nothing else, because #113 moved the page without
 * moving any of its contents. The rest arrives with #119 — the six-gate chain, how the canyon
 * works, how the Predictive Distribution was calibrated, the Face Height versus Significant
 * Wave Height distinction, ADR 0012 and the Proxy Target.
 *
 * **The rule that governs what lands here: teaching material moves, and limits that qualify a
 * number stay beside that number.** A redesign is exactly the change that quietly turns a
 * disclaimer into elegant grey fine print, so nothing whose job is to qualify a figure on the
 * forecast page may be relocated to this one.
 */

import { TrackRecordPage } from './TrackRecord';

export function HowItWorks() {
  return <TrackRecordPage />;
}
