/**
 * The second page: how the site decides, and how well it has done.
 *
 * #113 moved the page without moving any of its contents, and #119 is moving them: the swell
 * windows and their explanation are here, and the rest of the teaching material follows.
 *
 * **The rule that governs what lands here: teaching material moves, and limits that qualify a
 * number stay beside that number.** A redesign is exactly the change that quietly turns a
 * disclaimer into elegant grey fine print, so nothing whose job is to qualify a figure on the
 * forecast page may be relocated to this one.
 */

import { SwellWindowsSection } from './Forecast';
import { TrackRecordPage } from './TrackRecord';

export function HowItWorks() {
  return (
    <>
      <TrackRecordPage />

      {/* Arrived with #119, which moved it off the forecast page: spec §2 puts five things down
          that column and this was a sixth, and the verdict there already names the window a Go
          Call falls inside. The list and the paragraph explaining what a window is travel
          together, because a definition beside the thing it defines is the only place it reads
          as anything other than trivia. */}
      <SwellWindowsSection />
    </>
  );
}
