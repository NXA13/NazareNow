"""Write the design-canvas artboards from the real map and the stored gold-day decision.

The consoles are one template in three brand colours, so a colour comparison is a colour
comparison and not three slightly different layouts. Everything on them that is a number
comes from the scenario store, except the heights of the days that were not the Go Call,
which are marked as placeholders on the canvas.

Status colour and brand colour are deliberately different systems. A Go Call is a state
of the sea and keeps its pastel green whatever the wordmark does; the brand colour never
appears on a day row, so nothing on the page competes with the call for attention.
"""

from __future__ import annotations

from pathlib import Path

from build_map import GLYPHS, PALETTES, drift_seconds, keyframes, map_markup

HERE = Path(__file__).parent
OUT = HERE / "project"
OUT.mkdir(exist_ok=True)

FONTS = ("https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500;600"
         "&family=Space+Grotesk:wght@400;500;600;700&display=swap")

MONO = "'IBM Plex Mono', ui-monospace, monospace"
SANS = "'Space Grotesk', ui-sans-serif, system-ui, sans-serif"

# Only the 20th and 21st are real. See the canvas note.
DAYS = [
    ("Thu 17", "2.4", 30, "quiet"),
    ("Fri 18", "3.1", 39, "quiet"),
    ("Sat 19", "4.6", 58, "watch"),
    ("Sun 20", "6.4", 80, "go"),
    ("Mon 21", "5.9", 74, "go"),
    ("Tue 22", "3.8", 48, "watch"),
    ("Wed 23", "2.9", 36, "quiet"),
]
BEYOND = [
    ("Thu 24", "2.2", 28), ("Fri 25", "2.6", 33),
    ("Sat 26", "3.4", 43), ("Sun 27", "2.8", 35),
]

LEGEND_SPEEDS = [10, 25, 45]


def tile(palette: dict, label: str, value: str, unit: str) -> str:
    return (
        f'<div style="background:{palette["panel"]};border:1px solid {palette["border"]};'
        'border-radius:4px;padding:9px 10px;">'
        f'<div style="font-size:9.5px;letter-spacing:0.1em;text-transform:uppercase;'
        f'color:{palette["muted"]};">{label}</div>'
        f'<div style="font-family:{MONO};font-size:21px;font-weight:500;margin-top:3px;">'
        f'{value}<span style="font-size:12px;color:{palette["muted"]};">&nbsp;{unit}</span>'
        "</div></div>"
    )


def day_row(palette: dict, day: str, height: str, bar: int, kind: str) -> str:
    if kind == "go":
        border, background = palette["go"], palette["go_dim"]
        fill, label, weight, pad = palette["go"], "Go", "700", "9px"
        day_colour, status = palette["text"], palette["go"]
    elif kind == "watch":
        border, background = f'rgba(236,220,154,0.45)', palette["watch_dim"]
        fill, label, weight, pad = palette["watch"], "Watch", "600", "7px"
        day_colour, status = palette["text"], palette["watch"]
    else:
        border, background = palette["border"], palette["panel"]
        fill, label, weight, pad = palette["muted"], "Quiet", "400", "7px"
        day_colour, status = palette["muted"], palette["muted"]

    return (
        f'<button type="button" style="display:flex;align-items:center;gap:10px;width:100%;'
        f'text-align:left;font:inherit;color:{palette["text"]};background:{background};'
        f'border:1px solid {border};border-radius:3px;padding:{pad} 10px;cursor:pointer;">'
        f'<span style="width:58px;font-size:12px;color:{day_colour};">{day}</span>'
        f'<span style="width:52px;text-align:right;font-family:{MONO};font-size:'
        f'{"14px;font-weight:600" if kind == "go" else "12.5px"};">{height} m</span>'
        f'<span style="flex-grow:1;height:{7 if kind == "go" else 5}px;'
        'background:rgba(255,255,255,0.07);border-radius:4px;">'
        f'<span style="display:block;height:100%;width:{bar}%;background:{fill};'
        'border-radius:4px;"></span></span>'
        f'<span style="width:54px;text-align:right;font-size:9.5px;letter-spacing:0.08em;'
        f'text-transform:uppercase;color:{status};font-weight:{weight};">{label}</span>'
        "</button>"
    )


def faint_row(palette: dict, day: str, height: str, bar: int) -> str:
    return (
        f'<button type="button" style="display:flex;align-items:center;gap:10px;width:100%;'
        f'text-align:left;font:inherit;color:{palette["text"]};background:transparent;'
        f'border:1px dashed {palette["border"]};border-radius:3px;padding:6px 10px;'
        'cursor:pointer;">'
        f'<span style="width:58px;font-size:12px;color:{palette["muted"]};">{day}</span>'
        f'<span style="width:52px;text-align:right;font-family:{MONO};font-size:12px;'
        f'color:{palette["muted"]};">{height} m</span>'
        '<span style="flex-grow:1;height:4px;background:rgba(255,255,255,0.05);'
        'border-radius:3px;">'
        f'<span style="display:block;height:100%;width:{bar}%;background:{palette["muted"]};'
        'opacity:0.55;border-radius:3px;"></span></span>'
        f'<span style="width:54px;text-align:right;font-size:9.5px;text-transform:uppercase;'
        f'color:{palette["muted"]};opacity:0.8;">Quiet</span>'
        "</button>"
    )


def wind_scale(palette: dict, style: str) -> str:
    """The same glyph at three speeds, each drifting at the rate the rule gives it.

    Built from the map's own glyph function rather than a drawn copy, so a legend can
    never quietly disagree with the thing it is explaining -- and so the comet's tail and
    the barb's flags change across the three samples exactly as they do on the map.
    """
    samples = []
    for speed in LEGEND_SPEEDS:
        samples.append(
            '<span style="display:flex;flex-direction:column;align-items:center;gap:3px;">'
            '<svg width="22" height="40" viewBox="-13 -32 26 44" aria-hidden="true">'
            f'<g class="legend-dart" style="animation-duration:{drift_seconds(speed)}s;">'
            f'{GLYPHS[style](palette, speed)}</g></svg>'
            f'<span style="font-family:{MONO};font-size:8px;color:{palette["muted"]};">'
            f"{speed}</span></span>"
        )
    return (
        '<span style="display:flex;align-items:flex-end;gap:10px;">'
        + "".join(samples)
        + f'<span style="font-size:9px;color:{palette["muted"]};line-height:1.45;'
        'padding-bottom:3px;">km/h<br>faster wind,<br>faster drift</span></span>'
    )


LEGEND_KEYFRAMES = (
    "@keyframes legendDart{0%{opacity:0;transform:translateY(-9px)}"
    "22%{opacity:1}74%{opacity:1}100%{opacity:0;transform:translateY(9px)}}"
    ".legend-dart{animation-name:legendDart;animation-timing-function:linear;"
    "animation-iteration-count:infinite}"
)


def map_panel(palette: dict, key: str, style: str = "dart") -> str:
    return (
        f'<div style="flex-grow:1;position:relative;overflow:hidden;border:1px solid '
        f'{palette["border"]};border-radius:4px;background:{palette["deep"]};">'
        + map_markup(palette, key, wind_style=style) +
        f'<div style="position:absolute;left:14px;bottom:13px;display:flex;'
        f'flex-direction:column;gap:7px;background:rgba(0,0,0,0.6);border:1px solid '
        f'{palette["border"]};border-radius:3px;padding:9px 11px;">'
        f'<span style="display:flex;align-items:center;gap:7px;font-size:10px;'
        f'color:{palette["text"]};"><span style="width:20px;height:2px;'
        f'background:{palette["swell"]};"></span>Swell 310&deg; &middot; 13.75 s</span>'
        + wind_scale(palette, style) +
        f'<span style="font-size:9px;color:{palette["muted"]};max-width:216px;'
        'line-height:1.45;">One dart per forecast grid point. Crests brighten where the '
        'water shoals and the fronts start to bend.</span></div>'
        f'<div style="position:absolute;right:14px;top:12px;font-family:{MONO};'
        f'font-size:9.5px;letter-spacing:0.06em;color:{palette["muted"]};'
        f'background:rgba(0,0,0,0.6);border:1px solid {palette["border"]};'
        'border-radius:3px;padding:5px 8px;">GEBCO 2020 &middot; 20&ndash;1400 m</div>'
        "</div>"
    )


def console(key: str) -> str:
    palette = PALETTES[key]
    rows = "".join(day_row(palette, *day) for day in DAYS)
    beyond = "".join(faint_row(palette, *day) for day in BEYOND)

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>NazaréNow — {palette["name"]}</title>
<script src="./support.js"></script>
</head>
<body>
<x-dc>
<helmet>
  <link rel="stylesheet" href="{FONTS}">
  <style>
    body {{ margin: 0; background: {palette["page"]}; }}
    a {{ color: {palette["accent"]}; }}
    {keyframes(key)}
    {LEGEND_KEYFRAMES}
  </style>
</helmet>

<div style="width:1280px;height:820px;box-sizing:border-box;display:flex;
flex-direction:column;background:{palette["page"]};color:{palette["text"]};
font-family:{SANS};">

  <header style="height:62px;box-sizing:border-box;flex-shrink:0;display:flex;
  align-items:center;justify-content:space-between;padding:0 28px;
  border-bottom:1px solid {palette["border"]};">
    <div style="display:flex;align-items:baseline;gap:12px;">
      <span style="font-size:15px;font-weight:700;letter-spacing:0.17em;
      text-transform:uppercase;">Nazaré<span
      style="color:{palette["accent"]};">Now</span></span>
      <span style="font-size:11px;color:{palette["muted"]};">Praia do Norte, Portugal</span>
    </div>
    <nav style="display:flex;align-items:center;gap:22px;">
      <a href="#forecast" style="font-size:12px;font-weight:600;text-decoration:none;
      color:{palette["text"]};border-bottom:2px solid {palette["accent"]};
      padding-bottom:2px;">Forecast</a>
      <a href="#how" style="font-size:12px;text-decoration:none;
      color:{palette["muted"]};">How it works</a>
      <span style="font-family:{MONO};font-size:10.5px;color:{palette["muted"]};"
      >Updated 06:12 WEST</span>
    </nav>
  </header>

  <main style="flex-grow:1;display:flex;gap:20px;padding:20px 28px 22px;
  box-sizing:border-box;min-height:0;">

    <div style="width:604px;flex-shrink:0;display:flex;flex-direction:column;gap:12px;
    min-height:0;">

      <section style="background:{palette["go_dim"]};border:1px solid {palette["go"]};
      border-radius:4px;padding:16px 18px 17px;">
        <div style="font-family:{MONO};font-size:10.5px;letter-spacing:0.14em;
        text-transform:uppercase;color:{palette["go"]};font-weight:600;"
        >Go Call &middot; issued 4 days ahead</div>
        <h1 style="margin:6px 0 0;font-size:34px;line-height:1.05;letter-spacing:-0.02em;
        font-weight:700;">Book for Sun 20 Sept</h1>
        <p style="margin:9px 0 0;font-size:12.5px;line-height:1.5;
        color:{palette["muted"]};max-width:52ch;">Predicted <strong
        style="font-family:{MONO};color:{palette["text"]};">6.42&nbsp;m</strong>
        significant wave height, plausibly <strong style="font-family:{MONO};
        color:{palette["text"]};">4.28&ndash;8.79&nbsp;m</strong>. The independent wave
        models agree. Height only &mdash; period, direction and wind are not priced in
        this range.</p>
      </section>

      <section style="display:grid;grid-template-columns:repeat(4, minmax(0, 1fr));gap:8px;">
        {tile(palette, "Sig. wave", "5.62", "m")}
        {tile(palette, "Swell period", "13.75", "s")}
        {tile(palette, "Swell dir.", "310", "&deg; NW")}
        {tile(palette, "Wind", "12.6", "km/h")}
      </section>

      <section style="flex-grow:1;display:flex;flex-direction:column;gap:4px;min-height:0;">
        <div style="display:flex;align-items:baseline;justify-content:space-between;
        margin-bottom:2px;">
          <span style="font-size:10px;letter-spacing:0.12em;text-transform:uppercase;
          color:{palette["muted"]};font-weight:600;">Next 11 days</span>
          <span style="font-size:10px;color:{palette["muted"]};opacity:0.8;"
          >Measured accuracy to day 7</span>
        </div>
        {rows}
        <div style="display:flex;align-items:center;gap:8px;margin:5px 0 1px;">
          <span style="flex-grow:1;height:1px;background:{palette["border"]};"></span>
          <span style="font-size:9.5px;letter-spacing:0.1em;text-transform:uppercase;
          color:{palette["muted"]};">Beyond the measured archive</span>
          <span style="flex-grow:1;height:1px;background:{palette["border"]};"></span>
        </div>
        {beyond}
      </section>

      <p style="margin:0;font-size:11px;color:{palette["muted"]};line-height:1.5;
      border-top:1px solid {palette["border"]};padding-top:9px;">
        <strong style="font-family:{MONO};color:{palette["text"]};">258</strong> Go Calls
        checked against <strong style="font-family:{MONO};color:{palette["text"]};"
        >10,958</strong> reconstructed days &middot; <strong style="font-family:{MONO};
        color:{palette["text"]};">0.62&nbsp;m</strong> average height error &mdash;
        <a href="#how" style="font-weight:600;">how we know</a>
      </p>
    </div>

    {map_panel(palette, key)}
  </main>
</div>
</x-dc>
<script data-dc-script data-props='{{"$preview":{{"width":1280,"height":820}}}}'>
class Component extends DCLogic {{
  renderVals() {{ return {{}}; }}
}}
</script>
</body>
</html>
"""


WIND_NOTES = {
    "dart": "One sharp dart per forecast grid point, drifting downwind at 33 / speed "
            "seconds per hop. Speed is carried entirely by the motion, so a still frame "
            "of this map does not show it.",
    "comet": "A head with a tail whose length is the speed. Speed reads twice over — in "
             "the drift and in the glyph — so the map still says something in a "
             "screenshot, at the cost of more ink on the water.",
    "barb": "The meteorological wind barb: the staff points INTO the wind, half barb 5 kt, "
            "full barb 10 kt, pennant 50 kt. Exact, standard, and unreadable to anyone who "
            "has not met one before.",
}

WIND_TITLES = {"dart": "Darts", "comet": "Comets", "barb": "Wind barbs"}




def map_detail(key: str, style: str) -> str:
    """The map on its own, big enough to judge the bathymetry and the wind treatment."""
    palette = PALETTES[key]
    prefix = key + style.title()
    title = WIND_TITLES[style].lower()

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Nazaré Canyon — {title}</title>
<script src="./support.js"></script>
</head>
<body>
<x-dc>
<helmet>
  <link rel="stylesheet" href="{FONTS}">
  <style>
    body {{ margin: 0; background: {palette["deep"]}; }}
    {keyframes(prefix)}
    {LEGEND_KEYFRAMES}
  </style>
</helmet>

<div style="width:820px;height:940px;box-sizing:border-box;position:relative;
overflow:hidden;background:{palette["deep"]};color:{palette["text"]};font-family:{SANS};">
  {map_markup(palette, prefix, wind_style=style)}

  <div style="position:absolute;left:20px;top:18px;">
    <div style="font-size:10px;letter-spacing:0.16em;text-transform:uppercase;
    color:{palette["muted"]};">Wind &mdash; {title}</div>
    <div style="font-size:23px;font-weight:600;margin-top:3px;">Nazaré Canyon</div>
    <div style="font-family:{MONO};font-size:10px;color:{palette["muted"]};margin-top:4px;"
    >39.40&ndash;39.82&deg;N &middot; 9.04&ndash;9.52&deg;W</div>
  </div>

  <div style="position:absolute;right:20px;bottom:18px;display:flex;flex-direction:column;
  gap:6px;background:rgba(0,0,0,0.6);border:1px solid {palette["border"]};
  border-radius:3px;padding:10px 12px;">
    <span style="font-size:10px;letter-spacing:0.12em;text-transform:uppercase;
    color:{palette["muted"]};">Depth</span>
    <span style="display:block;width:170px;height:9px;background:linear-gradient(
    to right,{palette["deep"]},{palette["shelf"]});border:1px solid
    {palette["border"]};"></span>
    <span style="display:flex;justify-content:space-between;font-family:{MONO};
    font-size:9px;color:{palette["muted"]};"><span>1400 m</span><span>20 m</span></span>
  </div>

  <div style="position:absolute;left:20px;bottom:18px;max-width:350px;
  background:rgba(0,0,0,0.6);border:1px solid {palette["border"]};border-radius:3px;
  padding:11px 13px;display:flex;flex-direction:column;gap:9px;">
    <span style="display:flex;align-items:center;gap:8px;font-size:11px;
    color:{palette["text"]};"><span style="width:22px;height:2px;
    background:{palette["swell"]};"></span>Swell 310&deg; &middot; 13.75 s</span>
    {wind_scale(palette, style)}
    <span style="font-size:9.5px;line-height:1.5;color:{palette["muted"]};"
    >{WIND_NOTES[style]}</span>
  </div>
</div>
</x-dc>
<script data-dc-script data-props='{{"$preview":{{"width":820,"height":940}}}}'>
class Component extends DCLogic {{
  renderVals() {{ return {{}}; }}
}}
</script>
</body>
</html>
"""


def main() -> None:
    written = []
    (OUT / "Console-Ice.dc.html").write_text(console("ice"), encoding="utf-8")
    written.append("Console-Ice.dc.html")

    for style in ("dart", "comet", "barb"):
        name = f"Map-{style.title()}.dc.html"
        (OUT / name).write_text(map_detail("ice", style), encoding="utf-8")
        written.append(name)

    for name in written:
        print(f"  {name}  {(OUT / name).stat().st_size // 1024} kB")


if __name__ == "__main__":
    main()
