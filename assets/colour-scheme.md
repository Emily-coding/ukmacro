# Colour scheme: blue-amber

The house style for every ukmacro chart. The code that applies it is
`ukmacro/charts.py` (`THEMES["blue-amber"]`, `DEFAULT_THEME`); this file and
`colour-scheme.json` are for reusing the same look elsewhere (R, Excel, slides).

| Role | Hex |
|---|---|
| Series 1 | `#186FAF` blue |
| Series 2 | `#DE911D` amber |
| Series 3 | `#27AB83` teal |
| Series 4 | `#BA2525` red |
| "Not available" bars | `#9FB3C8` grey |
| Totals / reference lines, primary text | `#102A43` |
| Secondary text (units, legend, tick labels) | `#486581` |
| Axes ticks, source line | `#627D98` |
| Gridlines | `#D9E2EC` (hairline, horizontal only) |
| Zero line | `#9FB3C8` |
| Background | `#FFFFFF` |

Rules:
- Series colours in this fixed order; colour follows the series, never its value.
  A category keeps its colour across related charts (pin it with `"slot"`).
- More than 4 series: fold into "Other" or split into small multiples.
- Red is series 4 only: avoid it where it could read as "bad".
- Every pair passes a colour-blind check (worst simulated separation >= 8 in
  OKLab x100, normal-vision separation >= 15).

Font: Source Sans 3 (open licence, `assets/fonts/`). Titles semibold 16pt, units
11.5pt, legend 11pt, ticks 10.5pt, source 9pt. PNGs: 25 x 15 cm at 200 dpi.

Built from the Blue, Yellow Vivid, Teal, Red and Blue Grey scales of
svengraziani/ui-design's professional UI palettes.

## R (ggplot2)

```r
ukmacro_cols <- c("#186FAF", "#DE911D", "#27AB83", "#BA2525")
theme_ukmacro <- function(base_size = 11) {
  ggplot2::theme_minimal(base_size = base_size, base_family = "Source Sans 3") +
    ggplot2::theme(
      plot.title = ggplot2::element_text(colour = "#102A43", face = "bold", size = 16),
      plot.subtitle = ggplot2::element_text(colour = "#486581"),
      plot.caption = ggplot2::element_text(colour = "#627D98", size = 9, hjust = 0),
      axis.text = ggplot2::element_text(colour = "#486581"),
      panel.grid.major.y = ggplot2::element_line(colour = "#D9E2EC", linewidth = 0.3),
      panel.grid.major.x = ggplot2::element_blank(),
      panel.grid.minor = ggplot2::element_blank(),
      legend.position = "top", legend.justification = "left",
      plot.background = ggplot2::element_rect(fill = "#FFFFFF", colour = NA))
}
# ggplot(...) + scale_colour_manual(values = ukmacro_cols) + theme_ukmacro()
# ggsave("chart.png", width = 25, height = 15, units = "cm", dpi = 200)
```

## Python (matplotlib)

```python
from ukmacro import charts
charts.render(chart_json, "chart.png")            # uses the default theme
charts.THEMES["blue-amber"]["series"]             # the four series colours
```
