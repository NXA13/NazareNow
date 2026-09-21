/**
 * The wind across the map (#123).
 *
 * **One sharp dart per point the endpoint actually returned**, pointing downwind and drifting
 * along its own heading at `33 / speed` seconds per hop. Faster wind, faster drift.
 *
 * Darts were chosen over flowing streaks for an honesty reason as much as an aesthetic one:
 * this wind comes from twenty-five sampled points, and a continuous flow would imply a field
 * we do not have. One dart per fetched point is literally what the data is. Comets and
 * meteorological barbs were both built in the prototype and rejected.
 *
 * **Wind is the third colour system and stays quieter than the swell by design.** The base map
 * is greyscale so that colour means live data; the crests take Ice and the wind takes the
 * neutral warm grey, so a reader's eye goes to the swell first.
 *
 * The known cost, accepted when darts were chosen: **speed lives entirely in the motion**, so a
 * still frame shows direction and not strength.
 */

import { FRAME } from './depth-grid';
import { dartHeadingDeg, driftSeconds, toView } from './wind-rules';
import type { ConditionsGrid } from './api';

/**
 * The glyph, drawn once here and reused by the legend.
 *
 * Pointing along +x, so the group's `rotate` is the bearing and nothing has to reason about
 * the glyph's own orientation twice.
 *
 * **Sized against the frame, not against a hunch.** The viewBox is 686.8 units wide and renders
 * about 575 px at 1440x900, so a unit is roughly 0.84 px: the first draft's 7-unit dart came
 * out under 6 px and read as a smudge. Twelve units is about 10 px — legible, and still small
 * beside a crest that crosses the whole frame.
 */
const DART = 'M0,0L-12,-5L-8.5,0L-12,5Z';

function Dart({ x, y, headingDeg, seconds }: DartProps) {
  return (
    <g
      className="wind-dart"
      transform={`translate(${x} ${y}) rotate(${headingDeg})`}
      style={{ animationDuration: `${seconds}s` }}
    >
      <path d={DART} />
    </g>
  );
}

interface DartProps {
  x: number;
  y: number;
  headingDeg: number;
  seconds: number;
}

export function Wind({ grid }: { grid: ConditionsGrid | null }) {
  if (!grid) return null;
  return (
    <g className="wind" aria-hidden="true">
      {grid.points.map((point, index) => {
        const [x, y] = toView(point.latitude, point.longitude, FRAME);
        return (
          <Dart
            key={`${point.latitude},${point.longitude},${index}`}
            x={x}
            y={y}
            headingDeg={dartHeadingDeg(point.wind_direction.value)}
            seconds={driftSeconds(point.wind_speed.value)}
          />
        );
      })}
    </g>
  );
}

/** The speeds the legend samples. Three is enough to read the rate as a rate. */
const LEGEND_SPEEDS = [10, 25, 45];

/**
 * The key, drifting at the rates it names.
 *
 * **Built from the same `driftSeconds` the map uses**, so the legend cannot disagree with the
 * map: a legend with its own copy of the rule would go on looking right after the map's rule
 * changed, which is the failure a legend exists to prevent.
 */
export function WindLegend() {
  return (
    <ul className="wind-legend" aria-label="Wind speed">
      {LEGEND_SPEEDS.map((speed) => (
        <li key={speed}>
          <svg className="wind-legend-glyph" viewBox="-14 -6 20 12" aria-hidden="true">
            <g
              className="wind-dart"
              transform="translate(0 0)"
              style={{ animationDuration: `${driftSeconds(speed)}s` }}
            >
              <path d={DART} />
            </g>
          </svg>
          <span>{speed} km/h</span>
        </li>
      ))}
    </ul>
  );
}
