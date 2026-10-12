#!/usr/bin/env python3
"""Convert single-colour SVG icons to Android VectorDrawable XML (Python 3, stdlib only).

Usage (from the repository root)::

    py tools/svg_to_vector.py [SRC_DIR] [OUT_DIR]

    SRC_DIR  folder of *.svg files, default ``extended/icons``
    OUT_DIR  where ``ox_<stem>.xml`` is written,
             default ``android/app/src/main/res/drawable``

Every ``<stem>.svg`` becomes ``ox_<stem>.xml``: viewport 48x48 (taken from the SVG viewBox),
24dp x 24dp default size (callers size the Image), every path ``#FFFFFFFF`` so the icon can be tinted.

Supported SVG subset (anything else raises ValueError, it is never silently dropped):
  * ``<path d>``, ``<rect x y width height rx ry>``, ``<circle>``, ``<ellipse>``, ``<polygon>``, ``<g>`` (nested)
  * ``transform`` lists made of translate / rotate (optionally about a point) / scale / matrix. They are
    composed per element into one matrix and emitted as a ``<group>`` (translateX/Y, rotation, scaleX/Y,
    pivot 0,0). Skew is not supported (Android groups cannot express it).
  * opacity: ``opacity`` / ``fill-opacity`` attributes and CSS classes from a ``<style>`` block
    (``.cls-1 { opacity: .3 }``) become ``android:fillAlpha``; they multiply down nested groups.
  * ``fill="none"`` / ``display:none`` elements are skipped.

Not supported: strokes, gradients, clip paths, masks, <use>, text, images, CSS other than class selectors.
Colours are ignored on purpose (the icons are single-colour). An element that is exactly identical to an
earlier one (same geometry, transform and alpha) is dropped: Illustrator sometimes exports a layer twice,
which would otherwise stack the semi-transparent parts to a different opacity than intended.
"""
import math
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

SVG_NS = "http://www.w3.org/2000/svg"
IDENTITY = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)  # a b c d e f, as in SVG matrix(a b c d e f)
_NUM = re.compile(r"[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?")


class Shape:
    """One filled shape: SVG path data, composed transform matrix and fill alpha."""

    def __init__(self, path_data, matrix, alpha):
        self.path_data = path_data
        self.matrix = matrix
        self.alpha = alpha

    def key(self):
        return (self.path_data, tuple(round(v, 6) for v in self.matrix), round(self.alpha, 6))


def fmt(value):
    """Short decimal text: at most 4 decimals, no trailing zeros, no '-0'."""
    text = f"{value:.4f}".rstrip("0").rstrip(".")
    return "0" if text in ("", "-0") else text


def _local(tag):
    return tag.rsplit("}", 1)[-1]


def _numbers(text):
    return [float(m) for m in _NUM.findall(text or "")]


def _length(elem, name, default=0.0):
    raw = elem.get(name)
    if raw is None:
        return default
    nums = _numbers(raw)
    if not nums or raw.strip().endswith("%"):
        raise ValueError(f"unsupported {name}={raw!r} on <{_local(elem.tag)}>")
    return nums[0]


# --- transforms -----------------------------------------------------------------------------

def mat_mul(m, n):
    """m * n (n is applied first), both as (a, b, c, d, e, f)."""
    a1, b1, c1, d1, e1, f1 = m
    a2, b2, c2, d2, e2, f2 = n
    return (
        a1 * a2 + c1 * b2,
        b1 * a2 + d1 * b2,
        a1 * c2 + c1 * d2,
        b1 * c2 + d1 * d2,
        a1 * e2 + c1 * f2 + e1,
        b1 * e2 + d1 * f2 + f1,
    )


def parse_transform(text):
    """SVG transform list -> one matrix (a, b, c, d, e, f)."""
    result = IDENTITY
    if not text or not text.strip():
        return result
    pos = 0
    pattern = re.compile(r"\s*,?\s*([a-zA-Z]+)\s*\(([^)]*)\)")
    while pos < len(text):
        m = pattern.match(text, pos)
        if not m:
            if text[pos:].strip():
                raise ValueError(f"bad transform {text!r}")
            break
        pos = m.end()
        name, args = m.group(1), _numbers(m.group(2))
        if name == "translate" and len(args) in (1, 2):
            step = (1, 0, 0, 1, args[0], args[1] if len(args) == 2 else 0.0)
        elif name == "scale" and len(args) in (1, 2):
            step = (args[0], 0, 0, args[1] if len(args) == 2 else args[0], 0, 0)
        elif name == "rotate" and len(args) in (1, 3):
            rad = math.radians(args[0])
            cos, sin = math.cos(rad), math.sin(rad)
            step = (cos, sin, -sin, cos, 0, 0)
            if len(args) == 3:
                cx, cy = args[1], args[2]
                step = mat_mul(mat_mul((1, 0, 0, 1, cx, cy), step), (1, 0, 0, 1, -cx, -cy))
        elif name == "matrix" and len(args) == 6:
            step = tuple(args)
        else:
            raise ValueError(f"unsupported transform {name}({m.group(2)})")
        result = mat_mul(result, step)
    return result


def decompose(matrix):
    """Matrix -> (translateX, translateY, rotation degrees, scaleX, scaleY) for an Android <group>.

    Android applies translate * rotate * scale about the pivot (0, 0), which is exactly
    T(e, f) * R(theta) * S(sx, sy). Skew cannot be expressed: ValueError.
    """
    a, b, c, d, e, f = matrix
    sx = math.hypot(a, b)
    if sx < 1e-12:
        raise ValueError("degenerate transform")
    det = a * d - b * c
    sy = det / sx
    # With R(theta) S(sx, sy), column 2 must be sy * (-sin, cos) = sy * (-b/sx, a/sx).
    if abs(c - sy * (-b / sx)) > 1e-4 or abs(d - sy * (a / sx)) > 1e-4:
        raise ValueError("skew transforms are not supported")
    return e, f, math.degrees(math.atan2(b, a)), sx, sy


# --- shapes -> path data ----------------------------------------------------------------------

def rect_path(x, y, w, h, rx=0.0, ry=0.0):
    """Rect, with optional rounded corners (SVG rules: a missing radius copies the other, clamped to half size)."""
    if w <= 0 or h <= 0:
        raise ValueError("rect with non-positive size")
    rx, ry = abs(rx), abs(ry)
    if rx and not ry:
        ry = rx
    if ry and not rx:
        rx = ry
    rx, ry = min(rx, w / 2), min(ry, h / 2)
    n = fmt
    if rx == 0 or ry == 0:
        return f"M{n(x)},{n(y)}H{n(x + w)}V{n(y + h)}H{n(x)}Z"
    arc = f"A{n(rx)},{n(ry)},0,0,1,"
    return (
        f"M{n(x + rx)},{n(y)}H{n(x + w - rx)}{arc}{n(x + w)},{n(y + ry)}"
        f"V{n(y + h - ry)}{arc}{n(x + w - rx)},{n(y + h)}"
        f"H{n(x + rx)}{arc}{n(x)},{n(y + h - ry)}"
        f"V{n(y + ry)}{arc}{n(x + rx)},{n(y)}Z"
    )


def ellipse_path(cx, cy, rx, ry):
    if rx <= 0 or ry <= 0:
        raise ValueError("ellipse with non-positive radius")
    n = fmt
    return (
        f"M{n(cx - rx)},{n(cy)}"
        f"A{n(rx)},{n(ry)},0,1,0,{n(cx + rx)},{n(cy)}"
        f"A{n(rx)},{n(ry)},0,1,0,{n(cx - rx)},{n(cy)}Z"
    )


def circle_path(cx, cy, r):
    return ellipse_path(cx, cy, r, r)


def polygon_path(points):
    nums = _numbers(points)
    if len(nums) < 6 or len(nums) % 2:
        raise ValueError(f"bad polygon points {points!r}")
    pairs = [f"{fmt(nums[i])},{fmt(nums[i + 1])}" for i in range(0, len(nums), 2)]
    return "M" + "L".join(pairs) + "Z"


# --- css / opacity ----------------------------------------------------------------------------

def parse_css(css):
    """``.cls-1 { opacity: .3; fill: none }`` -> {'cls-1': {'opacity': '.3', 'fill': 'none'}}. Class selectors only."""
    rules = {}
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    for selectors, body in re.findall(r"([^{}]+)\{([^}]*)\}", css):
        props = {}
        for decl in body.split(";"):
            if ":" in decl:
                k, v = decl.split(":", 1)
                props[k.strip().lower()] = v.strip()
        for sel in selectors.split(","):
            sel = sel.strip()
            if re.fullmatch(r"\.[\w-]+", sel):
                rules.setdefault(sel[1:], {}).update(props)
            elif sel:
                raise ValueError(f"unsupported CSS selector {sel!r}")
    return rules


def _style_props(elem, css_rules):
    """Presentation attributes < class rules < inline style."""
    props = {}
    for name in ("opacity", "fill-opacity", "fill", "stroke", "display"):
        if elem.get(name) is not None:
            props[name] = elem.get(name).strip()
    for cls in (elem.get("class") or "").split():
        props.update(css_rules.get(cls, {}))
    for decl in (elem.get("style") or "").split(";"):
        if ":" in decl:
            k, v = decl.split(":", 1)
            props[k.strip().lower()] = v.strip()
    return props


def _opacity(props, key):
    raw = props.get(key)
    if raw is None:
        return 1.0
    nums = _numbers(raw)
    if not nums:
        raise ValueError(f"bad {key}={raw!r}")
    value = nums[0] / 100 if raw.strip().endswith("%") else nums[0]
    return max(0.0, min(1.0, value))


# --- document ---------------------------------------------------------------------------------

def convert_svg(text):
    """SVG text -> VectorDrawable XML text."""
    root = ET.fromstring(text)
    if _local(root.tag) != "svg":
        raise ValueError("root element is not <svg>")
    view_box = _numbers(root.get("viewBox") or "")
    if len(view_box) != 4 or view_box[0] != 0 or view_box[1] != 0:
        raise ValueError(f"unsupported viewBox {root.get('viewBox')!r} (need 0 0 W H)")
    vw, vh = view_box[2], view_box[3]

    css_rules = {}
    for style in root.iter():
        if _local(style.tag) == "style":
            css_rules.update(parse_css("".join(style.itertext())))

    shapes = []
    seen = set()

    def add(path_data, matrix, alpha):
        shape = Shape(path_data, matrix, alpha)
        if shape.key() not in seen:
            seen.add(shape.key())
            shapes.append(shape)

    def walk(elem, matrix, alpha):
        tag = _local(elem.tag)
        if tag in ("defs", "style", "title", "desc", "metadata"):
            return
        props = _style_props(elem, css_rules)
        if props.get("display") == "none" or props.get("fill") == "none":
            return
        if props.get("stroke", "none") != "none":
            raise ValueError(f"<{tag}> uses stroke, which is not supported")
        matrix = mat_mul(matrix, parse_transform(elem.get("transform")))
        alpha = alpha * _opacity(props, "opacity") * _opacity(props, "fill-opacity")
        if tag == "g":
            for child in elem:
                walk(child, matrix, alpha)
        elif tag == "path":
            d = elem.get("d")
            if not d or not d.strip():
                raise ValueError("<path> without d")
            add(" ".join(d.split()), matrix, alpha)
        elif tag == "rect":
            add(
                rect_path(
                    _length(elem, "x"), _length(elem, "y"), _length(elem, "width"), _length(elem, "height"),
                    _length(elem, "rx"), _length(elem, "ry"),
                ),
                matrix, alpha,
            )
        elif tag == "circle":
            add(circle_path(_length(elem, "cx"), _length(elem, "cy"), _length(elem, "r")), matrix, alpha)
        elif tag == "ellipse":
            add(
                ellipse_path(_length(elem, "cx"), _length(elem, "cy"), _length(elem, "rx"), _length(elem, "ry")),
                matrix, alpha,
            )
        elif tag == "polygon":
            add(polygon_path(elem.get("points")), matrix, alpha)
        else:
            raise ValueError(f"unsupported element <{tag}>")

    # The root <svg> may itself carry a class / opacity but never a transform.
    for child in root:
        walk(child, IDENTITY, 1.0)

    return render(vw, vh, shapes)


def render(vw, vh, shapes):
    lines = [
        '<?xml version="1.0" encoding="utf-8"?>',
        "<!-- Generated by tools/svg_to_vector.py from extended/icons: do not edit by hand. -->",
        '<vector xmlns:android="http://schemas.android.com/apk/res/android"',
        '    android:width="24dp"',
        '    android:height="24dp"',
        f'    android:viewportWidth="{fmt(vw)}"',
        f'    android:viewportHeight="{fmt(vh)}">',
    ]
    for shape in shapes:
        path = ['<path', '    android:fillColor="#FFFFFFFF"']
        if shape.alpha < 0.9999:
            path.append(f'    android:fillAlpha="{fmt(shape.alpha)}"')
        path.append(f'    android:pathData="{shape.path_data}" />')
        if shape.matrix == IDENTITY or all(abs(a - b) < 1e-9 for a, b in zip(shape.matrix, IDENTITY)):
            indent, wrap = "    ", False
        else:
            tx, ty, rot, sx, sy = decompose(shape.matrix)
            attrs = []
            if abs(rot) > 1e-6:
                attrs.append(f'android:rotation="{fmt(rot)}"')
            if abs(sx - 1) > 1e-6 or abs(sy - 1) > 1e-6:
                attrs.append(f'android:scaleX="{fmt(sx)}"')
                attrs.append(f'android:scaleY="{fmt(sy)}"')
            if abs(tx) > 1e-6:
                attrs.append(f'android:translateX="{fmt(tx)}"')
            if abs(ty) > 1e-6:
                attrs.append(f'android:translateY="{fmt(ty)}"')
            lines.append("    <group " + " ".join(attrs) + ">" if attrs else "    <group>")
            indent, wrap = "        ", True
        # A single-attribute-per-line <path>, like Android Studio writes it.
        lines.append(indent + path[0])
        lines.extend(indent + p for p in path[1:])
        if wrap:
            lines.append("    </group>")
    lines.append("</vector>")
    return "\n".join(lines) + "\n"


def convert_dir(src_dir, out_dir):
    """Convert every ``*.svg`` of [src_dir]; returns the written paths."""
    src_dir, out_dir = Path(src_dir), Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    written = []
    for svg in sorted(src_dir.glob("*.svg")):
        try:
            xml = convert_svg(svg.read_text(encoding="utf-8"))
        except (ValueError, ET.ParseError) as err:
            raise ValueError(f"{svg.name}: {err}") from err
        target = out_dir / f"ox_{svg.stem}.xml"
        target.write_text(xml, encoding="utf-8", newline="\n")
        written.append(target)
    return written


def main(argv):
    root = Path(__file__).resolve().parent.parent
    src = Path(argv[1]) if len(argv) > 1 else root / "extended" / "icons"
    out = Path(argv[2]) if len(argv) > 2 else root / "android" / "app" / "src" / "main" / "res" / "drawable"
    written = convert_dir(src, out)
    print(f"{len(written)} icons -> {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
