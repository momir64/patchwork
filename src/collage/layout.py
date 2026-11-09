"""Collage layout maths (no image work here, only aspect ratios in, rectangles out).

The old script put images into rows greedily, so the last row often held 2-3 images that were stretched far
taller than all other rows. Here the row breaks are chosen by dynamic programming so that *every* row (the
last one included) ends up as close as possible to the same height. With "auto-balance" several target
heights are tried and the most even result wins - the manual trial-and-error is done for you.
"""
import math
from dataclasses import dataclass, field


@dataclass
class Cell:
    x: int
    y: int
    w: int
    h: int
    index: int


@dataclass
class Layout:
    width: int
    height: int
    cells: list = field(default_factory=list)
    rows: int = 0
    row_height: int = 0
    spread: float = 0.0  # worst row, as fraction of the common row height (justified mode)
    fit: str = "crop"     # keep = images keep their shape; crop = images fill their cell

    def scaled(self, f: float) -> "Layout":
        cells = [Cell(round(c.x * f), round(c.y * f), max(1, round(c.w * f)), max(1, round(c.h * f)), c.index) for c in self.cells]
        return Layout(max(1, round(self.width * f)), max(1, round(self.height * f)), cells, self.rows,
                      round(self.row_height * f), self.spread, self.fit)


def _partition(ratios, prefix, avail, gap, target_h):
    """Split into rows so row heights stay near target_h. Returns list of (start, end)."""
    n = len(ratios)
    inf = float("inf")
    dp = [inf] * (n + 1)
    prev = [0] * (n + 1)
    dp[0] = 0.0
    for i in range(n):
        base = dp[i]
        if base == inf:
            continue
        for j in range(i + 1, n + 1):
            cnt = j - i
            usable = avail - gap * (cnt - 1)
            if usable <= 0:
                break
            h = usable / (prefix[j] - prefix[i])
            cost = base + math.log(h / target_h) ** 2
            if cost < dp[j]:
                dp[j] = cost
                prev[j] = i
            if h < target_h * 0.5:
                break
    rows, j = [], n
    while j > 0:
        rows.append((prev[j], j))
        j = prev[j]
    return rows[::-1]


def _row_heights(rows, prefix, avail, gap):
    return [(avail - gap * (j - i - 1)) / (prefix[j] - prefix[i]) for i, j in rows]


def _spans(weights, usable, gap, x0):
    """Integer x/width pairs that tile `usable` exactly."""
    total = sum(weights)
    edges, acc = [0], 0.0
    for w in weights:
        acc += w
        edges.append(round(usable * acc / total))
    return [(x0 + edges[k] + gap * k, edges[k + 1] - edges[k]) for k in range(len(weights))]


def justified(ratios, width, gap=4, margin=0, target_h=300, auto=True, equal_rows=True, aspect=0.0, keep=False, check=None) -> Layout:
    """aspect = wanted overall width/height of the collage (0 = free, use target_h instead).

    With an aspect, the number of rows and row height are searched so the finished collage lands on that shape;
    the last few pixels are absorbed by cropping posters very slightly (reported as `spread`).
    keep=True never crops: every row keeps its natural height, and with an aspect the row count / size is searched
    so the finished collage comes as close to that shape as the images allow."""
    n = len(ratios)
    if n == 0:
        return Layout(width, 2 * margin)
    avail = width - 2 * margin
    prefix = [0.0]
    for r in ratios:
        prefix.append(prefix[-1] + r)

    want_total = (width / aspect) if aspect else 0
    if aspect:
        # area argument: avail * (H_total - 2m) ~= sum(r) * h^2
        h0 = math.sqrt(max(1.0, avail * (want_total - 2 * margin) / prefix[-1]))
        candidates = [h0 * (0.6 + 0.9 * k / 60) for k in range(61)]
        equal_rows = not keep
    elif auto:
        candidates = [target_h * (0.7 + 0.6 * k / 40) for k in range(41)]
    else:
        candidates = [target_h]

    results = []
    for H in candidates:
        if check:
            check()                                   # may raise to stop early (a cancelled preview)
        rows = _partition(ratios, prefix, avail, gap, H)
        hs = _row_heights(rows, prefix, avail, gap)
        if aspect and keep:
            total = sum(hs) + gap * (len(rows) - 1) + 2 * margin
            ref = sum(hs) / len(hs)
            if ref < 4:
                continue
            results.append((max(abs(math.log(h / ref)) for h in hs) + 3 * abs(math.log(total / want_total)), rows, hs, ref))
            continue
        if aspect:
            ref = (want_total - 2 * margin - gap * (len(rows) - 1)) / len(rows)
            if ref < 4:
                continue
        else:
            ref = sum(hs) / len(hs)
        results.append((max(abs(math.log(h / ref)) for h in hs), rows, hs, ref))
    if aspect:
        best = min(results, key=lambda r: r[0])
    else:
        # among near-best candidates (within ~1% of the best evenness) stay closest to the requested row height
        limit = min(r[0] for r in results) * 1.5 + 0.01
        best = min((r for r in results if r[0] <= limit), key=lambda r: abs(math.log(r[3] / target_h)))
    _, rows, hs, ref = best

    cells, y, row_h = [], margin, []
    common = max(1, round(ref))
    for (i, j), h in zip(rows, hs):
        rh = common if equal_rows else max(1, round(h))
        row_h.append(rh)
        usable = avail - gap * (j - i - 1)
        for k, (x, w) in enumerate(_spans(ratios[i:j], usable, gap, margin)):
            cells.append(Cell(x, y, w, rh, i + k))
        y += rh + gap
    height = y - gap + margin
    spread = 0.0 if keep else max(abs(h / ref - 1) for h in hs)
    return Layout(width, height, cells, len(rows), common, spread, "keep" if keep else "crop")


def grid(ratios, width, gap=4, margin=0, cols=0, cell_aspect=None, center_last=True, aspect=0.0, keep=False) -> Layout:
    """Fixed grid. cols=0 picks the column count that best matches `aspect` (or a roughly square picture)."""
    n = len(ratios)
    if n == 0:
        return Layout(width, 2 * margin)
    cell_aspect = cell_aspect or sorted(ratios)[n // 2]
    avail = width - 2 * margin

    def shape(c):
        cw = (avail - gap * (c - 1)) / c
        ch = cw / cell_aspect
        rows = math.ceil(n / c)
        return rows, ch, 2 * margin + rows * ch + gap * (rows - 1)

    if cols <= 0:
        goal = aspect or 1.0
        cols = min(range(1, n + 1), key=lambda c: abs(math.log((width / shape(c)[2]) / goal)) if shape(c)[1] >= 4 else 9e9)
    cols = min(cols, n)
    rows, ch, total = shape(cols)
    if aspect and cols and abs(total - width / aspect) > 1:
        ch = (width / aspect - 2 * margin - gap * (rows - 1)) / rows  # stretch cells slightly to hit the shape exactly
    ch = max(1, round(ch))
    cw = (avail - gap * (cols - 1)) / cols
    spans = _spans([1] * cols, avail - gap * (cols - 1), gap, margin)
    cells = []
    for idx in range(n):
        r, c = divmod(idx, cols)
        x, w = spans[c]
        last = n - (rows - 1) * cols
        if center_last and r == rows - 1 and last < cols:
            x += round((cols - last) * (cw + gap) / 2)
        cells.append(Cell(x, margin + r * (ch + gap), w, ch, idx))
    spread = 0.0 if keep else abs((cw / ch) / cell_aspect - 1)
    return Layout(width, 2 * margin + rows * ch + gap * (rows - 1), cells, rows, ch, spread, "keep" if keep else "crop")
