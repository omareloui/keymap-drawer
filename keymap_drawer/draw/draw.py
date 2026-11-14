"""
Module that contains the KeymapDrawer class which takes a physical layout,
keymap with layers and optionally combo definitions, then can draw an SVG
representation of the keymap using these two.
"""

import logging
import re
from copy import deepcopy
from html import escape
from io import StringIO
from typing import Literal, Mapping, Sequence, TextIO

import yaml

from keymap_drawer.config import Config
from keymap_drawer.draw.combo import ComboDrawerMixin
from keymap_drawer.draw.utils import UtilsMixin
from keymap_drawer.keymap import ComboSpec, KeymapData, LayoutKey
from keymap_drawer.physical_layout import BOARD_OUTLINES_PATH, PhysicalKey, PhysicalLayout, Point

logger = logging.getLogger(__name__)


class KeymapDrawer(ComboDrawerMixin, UtilsMixin):
    """Class that draws a keyboard representation in SVG."""

    def __init__(self, config: Config, out: TextIO, **kwargs) -> None:
        self.cfg = config.draw_config
        self.keymap = KeymapData(config=config, **kwargs)
        self.init_glyphs()
        assert self.keymap.layout is not None, "A PhysicalLayout must be provided for drawing"
        assert self.keymap.config is not None, "A Config must be provided for drawing"
        self.layout = self.keymap.layout
        self.layer_names = set()
        self.output_stream = out
        self.out = StringIO()
        self.board_outline = self._load_board_outline(kwargs.get("layout") or {}) if self.cfg.draw_board else None

    def _load_board_outline(self, layout_spec: Mapping) -> tuple[Point, str] | None:
        """Return the origin (in pixels) and path data (in key units) of the keyboard body outline, if known."""
        keyboard = layout_spec.get("qmk_keyboard")
        with open(BOARD_OUTLINES_PATH, "rb") as f:
            outlines = yaml.safe_load(f)
        if keyboard not in outlines:
            logger.warning('draw_board is set but there is no body outline for keyboard "%s", skipping', keyboard)
            return None
        outline = outlines[keyboard]
        if (anchor := outline["anchor_key"]) >= len(self.layout.keys):
            logger.warning("draw_board is set but the physical layout has too few keys for the body outline, skipping")
            return None
        return self.layout.keys[anchor].pos, " ".join(outline["path"].split())

    def print_layer_header(self, p: Point, header: str) -> None:
        """Print a layer header that precedes the layer visualization."""
        text = header + ":" if self.cfg.append_colon_to_layer_header else header
        self.out.write(
            f'<text x="{round(p.x)}" y="{round(p.y)}" class="label" id="{self._str_to_id(header)}">{escape(text)}</text>\n'
        )

    def print_footer(self, p: Point) -> None:
        """Print a footer with text given by cfg.footer_text, with CSS class `footer` for bottom-right alignment."""
        self.output_stream.write(
            f'<text x="{p.x - self.cfg.outer_pad_w}" y="{p.y - self.cfg.outer_pad_h / 2}" class="footer">'
            f"{self.cfg.footer_text}</text>"
        )

    def print_key(self, p_key: PhysicalKey, l_key: LayoutKey, key_ind: int) -> None:
        """
        Print SVG code for a rectangle with text representing the key, which is described by its physical
        representation (p_key) and what it does in the given layer (l_key).
        """
        p, w, h = (
            p_key.pos,
            p_key.width,
            p_key.height,
        )
        rotate_str = f" rotate({p_key.rotation})" if p_key.rotation != 0 else ""
        transform_attr = f' transform="translate({round(p.x)}, {round(p.y)}){rotate_str}"'
        class_str = self._to_class_str(["key", l_key.type, f"keypos-{key_ind}"])
        self.out.write(f"<g{transform_attr}{class_str}>\n")

        self._draw_key(Point(w - 2 * self.cfg.inner_pad_w, h - 2 * self.cfg.inner_pad_h), classes=["key", l_key.type])
        if p_key.is_iso_enter:
            self.out.write(
                f'<g transform="translate({round(-w / 10)}, {round(-h / 4)})" '
                'style="clip-path: polygon(-5% -5%, 58.34% -5%, 16.67% 105%, 0% 105%)">\n'
            )
            self._draw_key(
                Point(w * 6 / 5 - 2 * self.cfg.inner_pad_w, h / 2 - 2 * self.cfg.inner_pad_h),
                classes=["key", l_key.type],
            )
            self.out.write("</g>\n")

        tap_words = self._split_text(l_key.tap, truncate=3, line_width=self.cfg.shrink_wide_legends)

        # auto-adjust vertical alignment up/down if there are two lines and either hold/shifted is present
        shift = 0
        if len(tap_words) == 2:
            if l_key.shifted and not l_key.hold:  # shift down
                shift = -1
            elif l_key.hold and not l_key.shifted:  # shift up
                shift = 1

        # auto-shift middle legend if key sides are drawn
        tap_shift = Point(self.cfg.legend_rel_x, self.cfg.legend_rel_y)
        if self.cfg.draw_key_sides:
            tap_shift -= Point(self.cfg.key_side_pars.rel_x, self.cfg.key_side_pars.rel_y)

        x_offset = w / 2 - self.cfg.inner_pad_w - self.cfg.small_pad
        y_offset = h / 2 - self.cfg.inner_pad_h - self.cfg.small_pad

        self._draw_legend(
            tap_shift,
            tap_words,
            classes=["key", l_key.type],
            legend_type="tap",
            shift=shift,
        )
        self._draw_legend(
            Point(0, y_offset),
            [l_key.hold],
            classes=["key", l_key.type],
            legend_type="hold",
        )
        self._draw_legend(
            Point(0, -y_offset),
            [l_key.shifted],
            classes=["key", l_key.type],
            legend_type="shifted",
        )
        self._draw_legend(
            Point(-x_offset, 0),
            [l_key.left],
            classes=["key", l_key.type],
            legend_type="left",
        )
        self._draw_legend(
            Point(x_offset, 0),
            [l_key.right],
            classes=["key", l_key.type],
            legend_type="right",
        )

        # corner legends
        self._draw_legend(
            Point(-x_offset, -y_offset),
            [l_key.tl],
            classes=["key", l_key.type],
            legend_type="tl",
        )
        self._draw_legend(
            Point(x_offset, -y_offset),
            [l_key.tr],
            classes=["key", l_key.type],
            legend_type="tr",
        )
        self._draw_legend(
            Point(-x_offset, y_offset),
            [l_key.bl],
            classes=["key", l_key.type],
            legend_type="bl",
        )
        self._draw_legend(
            Point(x_offset, y_offset),
            [l_key.br],
            classes=["key", l_key.type],
            legend_type="br",
        )

        self.out.write("</g>\n")

    @staticmethod
    def _path_points(path: str) -> list[Point]:
        """Return the end and control points of an SVG path made of absolute commands, for bounding box purposes."""
        points: list[Point] = []
        cur = Point(0.0, 0.0)
        for cmd, args_str in re.findall(r"([A-Za-z])([^A-Za-z]*)", path):
            args = [float(a) for a in re.findall(r"[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?", args_str)]
            match cmd:
                case "H":
                    coords = [Point(x, cur.y) for x in args]
                case "V":
                    coords = [Point(cur.x, y) for y in args]
                case "A":  # rx ry rotation large-arc sweep x y
                    coords = []
                    for i in range(0, len(args) - 6, 7):
                        rx, ry, end = args[i], args[i + 1], Point(args[i + 5], args[i + 6])
                        # conservatively include the arc's possible extent around both endpoints
                        r = max(rx, ry)
                        coords += [end, cur + Point(r, r), cur - Point(r, r), end + Point(r, r), end - Point(r, r)]
                        cur = end
                case "Z" | "z":
                    coords = []
                case _ if cmd.isupper():
                    coords = [Point(args[i], args[i + 1]) for i in range(0, len(args) - 1, 2)]
                case _:
                    raise ValueError(f'Only absolute commands are supported in trackball housing paths, got "{cmd}"')
            if coords and cmd != "A":
                cur = coords[-1]
            points += coords
        return points

    def extras_bounds(self) -> tuple[Point, Point]:
        """Return the top left and bottom right coordinates covered by the body outline and trackballs, in pixels."""
        points = []
        if self.board_outline is not None:
            origin, path = self.board_outline
            points += [origin + p * self.cfg.key_h for p in self._path_points(path)]
        for t in self.cfg.trackballs:
            center = Point(t.x, t.y)
            points += [(center - Point(t.r, t.r)) * self.cfg.key_h, (center + Point(t.r, t.r)) * self.cfg.key_h]
            if t.draw_housing:
                points += [(center + p) * self.cfg.key_h for p in self._path_points(t.housing)]
        if not points:
            return Point(0.0, 0.0), Point(0.0, 0.0)
        return (
            Point(min(p.x for p in points), min(p.y for p in points)),
            Point(max(p.x for p in points), max(p.y for p in points)),
        )

    def print_board_outline(self) -> None:
        """Print SVG code for the keyboard body outline, if enabled and known."""
        if self.board_outline is None:
            return
        origin, path = self.board_outline
        self.out.write(
            f'<path d="{escape(path)}" transform="translate({round(origin.x, 2)}, {round(origin.y, 2)}) '
            f'scale({self.cfg.key_h})" vector-effect="non-scaling-stroke" class="board"/>\n'
        )

    def print_trackballs(self, layer_name: str, part: Literal["housing", "ball"]) -> None:
        """
        Print SVG code for the trackballs configured to be drawn on the given layer. Housings and balls (with their
        rings) are printed in separate passes so that the keyboard body can be drawn between them.
        """
        for ind, trackball in enumerate(self.cfg.trackballs):
            if trackball.layers and layer_name not in trackball.layers:
                continue
            if part == "housing" and not (trackball.housing and trackball.draw_housing):
                continue
            center = Point(trackball.x, trackball.y) * self.cfg.key_h
            self.out.write(
                f'<g transform="translate({round(center.x)}, {round(center.y)})" class="trackball trackball-{ind}">\n'
            )
            if part == "housing":
                self.out.write(
                    f'<path d="{escape(trackball.housing)}" transform="scale({self.cfg.key_h})" '
                    'vector-effect="non-scaling-stroke" class="trackball-housing"/>\n'
                )
            else:
                radius = trackball.r * self.cfg.key_h - self.cfg.inner_pad_w
                self.out.write(f'<circle r="{round(radius)}" class="trackball"/>\n')
                self.out.write(f'<circle r="{round(radius * trackball.ball_ratio)}" class="trackball-ball"/>\n')
                self._draw_legend(Point(0, 0), [trackball.legend], classes=["trackball"], legend_type="tap")
            self.out.write("</g>\n")

    def print_layers(  # pylint: disable=too-many-locals,too-many-arguments
        self,
        p: Point,
        layout: PhysicalLayout,
        layers: Mapping[str, Sequence[LayoutKey]],
        combos_per_layer: Mapping[str, Sequence[ComboSpec]],
        n_cols: int = 1,
        draw_header: bool = True,
        pad_divisor: int = 1,
        draw_extras: bool = True,
    ) -> Point:
        """
        Print SVG code for keys for all layers (including combos on them) starting at coordinate p,
        into n_cols columns and return the bottom right coordinate.
        """
        outer_pad_w = self.cfg.outer_pad_w // pad_divisor
        p += Point(self.cfg.outer_pad_w - outer_pad_w, 0)
        original_x = p.x
        # extras are the keyboard body outline and trackballs, which can extend past the keys in any direction
        extras_min, extras_max = self.extras_bounds() if draw_extras else (Point(0.0, 0.0), Point(0.0, 0.0))
        left_x = min(0.0, extras_min.x)
        layout_width = max(layout.width, extras_max.x) - left_x
        layout_height = max(layout.height, extras_max.y)
        col_width = layout_width + 2 * outer_pad_w
        max_height = 0.0
        for ind, (name, layer_keys) in enumerate(layers.items()):
            outer_pad_h = self.cfg.outer_pad_h // pad_divisor if ind > n_cols - 1 else self.cfg.outer_pad_h

            # per-layer class group
            self.out.write(
                f'<g transform="translate({round(p.x + outer_pad_w)}, {round(p.y)})" class="layer-{escape(name)}">\n'
            )

            # draw layer name
            if draw_header:
                self.print_layer_header(Point(0, outer_pad_h / 2), name)

            # back up main buffer, create and start writing to a temp output buffer
            with StringIO() as temp_buffer:
                writer = self.out
                self.out = temp_buffer

                # draw trackball housings, body outline and trackballs to temp buffer, in that order (housings sit
                # under the keyboard body), before the keys so that keys are drawn over them
                if draw_extras:
                    self.print_trackballs(name, "housing")
                    self.print_board_outline()
                    self.print_trackballs(name, "ball")

                # draw keys to temp buffer
                for key_ind, (p_key, l_key) in enumerate(zip(layout.keys, layer_keys)):
                    self.print_key(p_key, l_key, key_ind)

                # draw combos to temp buffer and calculate top/bottom y coordinates
                min_y, max_y = self.print_combos_for_layer(combos_per_layer.get(name, []))
                top_y = min(0.0, extras_min.y) if min_y is None else min(0.0, extras_min.y, min_y)
                bottom_y = layout_height if max_y is None else max(layout_height, max_y)

                # shift by the top y coordinate, then dump the temp buffer
                writer.write(f'<g transform="translate({round(-left_x)}, {round(outer_pad_h - top_y)})">\n')
                writer.write(temp_buffer.getvalue())
                writer.write("</g>\n")
                writer.write("</g>\n")
            self.out = writer

            max_height = max(max_height, bottom_y - top_y)

            if ind % n_cols == n_cols - 1 or ind == len(layers) - 1:
                p = Point(original_x, p.y + outer_pad_h + max_height)
                max_height = 0.0
            else:
                p += Point(col_width, 0)

        return Point(original_x + col_width * n_cols, p.y)

    def print_board(  # pylint: disable=too-many-locals
        self,
        draw_layers: Sequence[str] | None = None,
        keys_only: bool = False,
        combos_only: bool = False,
        ghost_keys: Sequence[int] | None = None,
    ) -> None:
        """Print SVG code representing the keymap."""
        # get final set of layers and combos per layer given the drawing options
        layers, combos_per_layer = _resolve_layers_combos(self.keymap, draw_layers, keys_only, combos_only, ghost_keys)

        self.layer_names = set(layers)

        # write to internal output stream self.out
        p = self.print_layers(Point(0, 0), self.layout, layers, combos_per_layer, self.cfg.n_columns)

        if not keys_only:
            layout, combo_layers = self.create_combo_diagrams(self.cfg.combo_diagrams_scale, ghost_keys)
            if layout is not None and combo_layers:
                self.print_layer_header(Point(self.cfg.outer_pad_w, p.y + self.cfg.outer_pad_h / 2), "Combos")
                p = self.print_layers(
                    Point(0, p.y),
                    layout,
                    combo_layers,
                    combos_per_layer,
                    self.cfg.n_columns * self.cfg.combo_diagrams_scale,
                    draw_header=False,
                    pad_divisor=self.cfg.combo_diagrams_scale,
                    draw_extras=False,
                )

        # write to final output stream self.output_stream
        board_w, board_h = round(p.x), round(p.y + self.cfg.outer_pad_h)
        self.output_stream.write(
            f'<svg width="{board_w}" height="{board_h}" viewBox="0 0 {board_w} {board_h}" class="keymap" '
            'xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink">\n'
        )
        self.output_stream.write(self.get_glyph_defs())

        dark_style = ""
        if self.cfg.dark_mode == "auto" and self.cfg.svg_style_dark:
            dark_style = f"\n@media (prefers-color-scheme: dark) {{\n{self.cfg.svg_style_dark}\n}}"
        elif self.cfg.dark_mode is True and self.cfg.svg_style_dark:
            dark_style = f"\n{self.cfg.svg_style_dark}"
        extra_style = f"\n{self.cfg.svg_extra_style}" if self.cfg.svg_extra_style else ""

        self.output_stream.write(f"<style>{self.cfg.svg_style}{dark_style}{extra_style}</style>\n")
        self.output_stream.write(self.out.getvalue())

        if self.cfg.footer_text:
            self.print_footer(Point(board_w, board_h))

        self.output_stream.write("</svg>\n")


def _resolve_layers_combos(
    keymap: KeymapData,
    draw_layers: Sequence[str] | None = None,
    keys_only: bool = False,
    combos_only: bool = False,
    ghost_keys: Sequence[int] | None = None,
) -> tuple[dict[str, list[LayoutKey]], dict[str, list[ComboSpec]]]:
    layers = deepcopy(keymap.layers)
    if draw_layers:
        assert all(l in layers for l in draw_layers), "Some layer names selected for drawing are not in the keymap"
        layers = {name: layer for name, layer in layers.items() if name in draw_layers}

    if keys_only:
        combos_per_layer: dict[str, list[ComboSpec]] = {}
    elif not layers:
        combos_per_layer = {"Combos": keymap.combos}
    else:
        combos_per_layer = keymap.get_combos_per_layer(layers)

    assert keymap.layout is not None

    if combos_only or not layers:
        layers = {
            name: [LayoutKey() for _ in range(len(keymap.layout))]
            for name, combos in combos_per_layer.items()
            if combos
        }

    if ghost_keys:
        for key_position in ghost_keys:
            assert (
                0 <= key_position < len(keymap.layout)
            ), "Some key positions for `ghost_keys` are negative or too large for the layout"
            for layer in layers.values():
                layer[key_position].type = "ghost"

    return layers, combos_per_layer
