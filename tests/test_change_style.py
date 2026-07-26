"""Unit tests for the Change_Style table, node decoration and label decoration.

The change state is drawn on the whole node — a coloured border plus a light
tinted background around the icon and the text — while the label only carries
the coloured Flag_Token, so a monochrome print still reads the Change_Category.

Covers Requirements 4.6, 5.1, 5.2, 5.3, 5.4, 5.9 and 10.2.
"""

import logging
import re

import pytest

from utils.change_style import (
    CHANGE_STYLES,
    LEGEND_TITLE,
    NODE_DECORATION_KEYS,
    NODE_PENWIDTH,
    ChangeStyle,
    decorate_label,
    legend_label,
    node_style_attributes,
    reset_style_warnings,
    resolve_style,
)

#: The Change_Style table as designed: category -> (colour token, Flag_Token, tint).
EXPECTED_STYLES = {
    "create": ("#107C10", "+", "#DBEBDB"),
    "update": ("#0078D4", "~", "#D9EBF9"),
    "replace": ("#D13438", "±", "#F8E1E1"),
    "delete": ("#D13438", "-", "#F8E1E1"),
}


def channels(token: str):
    """Return the three 8-bit channels of a ``#RRGGBB`` colour token."""
    assert re.fullmatch(r"#[0-9A-F]{6}", token), token
    return tuple(int(token[index : index + 2], 16) for index in (1, 3, 5))


def legacy_label(label: str, resource_type: str) -> str:
    """Reproduce the label that add_node_in_subgraph builds today."""
    return (
        f"<<TABLE border='0' cellborder='0' cellspacing='0'>"
        f"<TR><TD>{label}</TD></TR><TR><TD>{resource_type}</TD></TR></TABLE>>"
    )


def label_text(decorated: str) -> str:
    """Strip every HTML-like tag from a Graphviz label, keeping only its text."""
    return re.sub(r"<[^>]*>", " ", decorated[1:-1])


class _RecordCollector(logging.Handler):
    """Collect log records straight off the module logger (it does not propagate)."""

    def __init__(self):
        super().__init__(level=logging.WARNING)
        self.messages = []

    def emit(self, record):
        self.messages.append(record.getMessage())


@pytest.fixture
def warnings_log():
    """Capture warnings emitted by utils.change_style."""
    from utils import change_style

    handler = _RecordCollector()
    change_style.logger.addHandler(handler)
    try:
        yield handler.messages
    finally:
        change_style.logger.removeHandler(handler)


@pytest.fixture(autouse=True)
def _clear_warnings():
    reset_style_warnings()
    yield
    reset_style_warnings()


class TestChangeStyleTable:
    """The colour token and Flag_Token of every Change_Category."""

    @pytest.mark.parametrize("category,color,flag", [(c, s[0], s[1]) for c, s in EXPECTED_STYLES.items()])
    def test_table_maps_each_category_to_its_colour_and_flag(self, category, color, flag):
        style = CHANGE_STYLES[category]
        assert (style.color, style.flag) == (color, flag)

    @pytest.mark.parametrize("category,color,tint", [(c, s[0], s[2]) for c, s in EXPECTED_STYLES.items()])
    def test_table_maps_each_category_to_its_background_tint(self, category, color, tint):
        """The tint is the designed colour token blended 15% into white."""
        style = CHANGE_STYLES[category]
        assert style.tint == tint
        assert style.tint != style.color
        # Blended towards white: every channel is lighter than the colour token's
        # and none is pure white, so the fill stays visible and the icon readable.
        assert all(
            colour_channel < tint_channel < 0xFF
            for colour_channel, tint_channel in zip(channels(color), channels(tint))
        )

    def test_categories_sharing_a_colour_share_its_tint(self):
        """`replace` and `delete` are the same colour, so the same tint."""
        assert CHANGE_STYLES["replace"].color == CHANGE_STYLES["delete"].color
        assert CHANGE_STYLES["replace"].tint == CHANGE_STYLES["delete"].tint

    def test_unchanged_carries_no_style(self):
        assert "unchanged" in CHANGE_STYLES
        assert CHANGE_STYLES["unchanged"] is None

    def test_table_covers_exactly_the_change_category_set(self):
        from core.plan_diff import CHANGE_CATEGORIES

        assert set(CHANGE_STYLES) == set(CHANGE_CATEGORIES)

    def test_styles_are_immutable(self):
        with pytest.raises(Exception):
            CHANGE_STYLES["create"].color = "#000000"


class TestResolveStyle:
    """resolve_style returns None for legacy, unchanged and unknown values."""

    def test_none_resolves_to_no_style(self):
        assert resolve_style(None) is None

    def test_unchanged_resolves_to_no_style(self):
        assert resolve_style("unchanged") is None

    @pytest.mark.parametrize("category", ["create", "update", "replace", "delete"])
    def test_known_categories_resolve_to_their_style(self, category):
        assert resolve_style(category) is CHANGE_STYLES[category]

    def test_unknown_category_resolves_to_no_style_with_a_warning(self, warnings_log):
        assert resolve_style("obliterate") is None
        assert any("obliterate" in message for message in warnings_log)

    def test_unknown_category_warns_once_per_value(self, warnings_log):
        resolve_style("obliterate")
        resolve_style("obliterate")
        resolve_style("obliterate")
        assert len([m for m in warnings_log if "obliterate" in m]) == 1

    def test_distinct_unknown_categories_each_warn_once(self, warnings_log):
        resolve_style("obliterate")
        resolve_style("mutate")
        resolve_style("obliterate")
        assert len([m for m in warnings_log if "obliterate" in m]) == 1
        assert len([m for m in warnings_log if "mutate" in m]) == 1

    def test_unchanged_never_warns(self, warnings_log):
        resolve_style("unchanged")
        resolve_style(None)
        assert warnings_log == []

    def test_unhashable_category_resolves_to_no_style_with_a_warning(self, warnings_log):
        assert resolve_style(["delete"]) is None
        assert len(warnings_log) == 1


class TestDecorateLabel:
    """decorate_label only prepends the coloured Flag_Token to the first cell."""

    def test_delete_label_matches_the_designed_shape(self):
        decorated = decorate_label(legacy_label("app-web", "sites"), CHANGE_STYLES["delete"])
        assert decorated == (
            "<<TABLE border='0' cellborder='0' cellspacing='0'>"
            "<TR><TD><FONT COLOR='#D13438'><B>-</B></FONT> app-web</TD></TR>"
            "<TR><TD>sites</TD></TR></TABLE>>"
        )

    @pytest.mark.parametrize("category", ["create", "update", "replace", "delete"])
    def test_decoration_is_exactly_the_flag_markup_in_the_first_cell(self, category):
        """The label gains the Flag_Token markup and nothing else, byte for byte."""
        style = CHANGE_STYLES[category]
        legacy = legacy_label("app-web", "sites")
        decorated = decorate_label(legacy, style)
        flag_markup = f"<FONT COLOR='{style.color}'><B>{style.flag}</B></FONT> "

        assert decorated == legacy.replace("<TD>app-web", "<TD>" + flag_markup + "app-web")
        # The table itself is untouched: same attributes, no border, no table colour.
        assert decorated.startswith("<<TABLE border='0' cellborder='0' cellspacing='0'>")

    @pytest.mark.parametrize("category", ["create", "update", "replace", "delete"])
    def test_colour_token_and_flag_token_are_both_present(self, category):
        style = CHANGE_STYLES[category]
        decorated = decorate_label(legacy_label("app-web", "sites"), style)
        assert decorated.count(style.color) == 1  # the flag font only
        assert f"<B>{style.flag}</B>" in decorated

    @pytest.mark.parametrize("category", ["create", "update", "replace", "delete"])
    def test_label_carries_no_border_and_no_tint(self, category):
        """The border and the background belong to the node, not to the label."""
        style = CHANGE_STYLES[category]
        legacy = legacy_label("app-web", "sites")
        decorated = decorate_label(legacy, style)

        assert style.tint not in decorated
        # Exactly the attribute names the Legacy_Mode table already had.
        assert decorated.count("border=") == legacy.count("border=") == 2  # border + cellborder
        assert "border='1'" not in decorated
        assert decorated.count("color=") == legacy.count("color=") == 0  # no table colour
        assert decorated.count("COLOR=") == 1  # the flag font colour

    def test_flag_token_is_label_text_not_only_a_colour_attribute(self):
        """Requirement 5.9: readable in a monochrome print."""
        decorated = decorate_label(legacy_label("app-web", "sites"), CHANGE_STYLES["create"])
        assert "+" in label_text(decorated)

    def test_structure_and_content_are_preserved(self):
        decorated = decorate_label(legacy_label("app-web", "sites"), CHANGE_STYLES["update"])
        assert decorated.startswith("<<TABLE") and decorated.endswith("</TABLE>>")
        assert decorated.count("<TR>") == 2
        assert "app-web" in decorated
        assert "<TR><TD>sites</TD></TR>" in decorated
        assert "cellborder='0'" in decorated
        assert "cellspacing='0'" in decorated

    def test_only_the_first_cell_receives_the_flag(self):
        decorated = decorate_label(legacy_label("app-web", "sites"), CHANGE_STYLES["delete"])
        assert decorated.count("<B>-</B>") == 1

    def test_label_carries_no_attribute_values(self):
        """Requirement 10.2: the label holds name, short type and flag only."""
        decorated = decorate_label(legacy_label("app-web", "sites"), CHANGE_STYLES["replace"])
        assert set(label_text(decorated).split()) == {"±", "app-web", "sites"}

    def test_label_without_a_table_still_gains_the_flag_token(self):
        decorated = decorate_label("plain-label", CHANGE_STYLES["create"])
        assert "<B>+</B>" in decorated
        assert "plain-label" in decorated

    def test_existing_table_attributes_are_left_alone(self):
        """Table attributes are no longer rewritten: only the cell changes."""
        label = "<<TABLE border='0' color='#FFFFFF' cellborder='0'><TR><TD>x</TD></TR></TABLE>>"
        decorated = decorate_label(label, CHANGE_STYLES["update"])
        assert decorated == (
            "<<TABLE border='0' color='#FFFFFF' cellborder='0'>"
            "<TR><TD><FONT COLOR='#0078D4'><B>~</B></FONT> x</TD></TR></TABLE>>"
        )
        assert "#FFFFFF" in decorated  # the caller's table colour survives
        assert decorated.count("border=") == 2  # border + cellborder, none added
        assert decorated.count("COLOR=") == 1  # one flag font colour

    def test_table_without_a_border_attribute_gains_none(self):
        decorated = decorate_label("<<TABLE><TR><TD>x</TD></TR></TABLE>>", CHANGE_STYLES["delete"])
        assert decorated == "<<TABLE><TR><TD><FONT COLOR='#D13438'><B>-</B></FONT> x</TD></TR></TABLE>>"
        assert "border=" not in decorated

    def test_cell_attributes_are_preserved(self):
        """The Flag_Token goes inside the first cell, after its attributes."""
        label = "<<TABLE border='0'><TR><TD ALIGN='LEFT'>x</TD></TR></TABLE>>"
        decorated = decorate_label(label, CHANGE_STYLES["create"])
        assert decorated == (
            "<<TABLE border='0'><TR><TD ALIGN='LEFT'>"
            "<FONT COLOR='#107C10'><B>+</B></FONT> x</TD></TR></TABLE>>"
        )


class TestNodeStyleAttributes:
    """node_style_attributes draws the change state over the whole node."""

    @pytest.mark.parametrize("category", ["create", "update", "replace", "delete"])
    def test_decorated_category_yields_the_designed_attributes(self, category):
        style = CHANGE_STYLES[category]
        assert node_style_attributes(style) == {
            "shape": "box",
            "style": "filled,rounded",
            "color": style.color,
            "fillcolor": style.tint,
            "penwidth": NODE_PENWIDTH,
        }

    @pytest.mark.parametrize("category", ["create", "update", "replace", "delete"])
    def test_border_carries_the_colour_and_the_fill_carries_the_tint(self, category):
        """The colour token is the border, the tint is the background."""
        style = CHANGE_STYLES[category]
        attributes = node_style_attributes(style)

        assert attributes["color"] == style.color
        assert attributes["fillcolor"] == style.tint
        assert attributes["color"] != attributes["fillcolor"]
        # The fill is painted, and the box is the only thing that draws it.
        assert "filled" in attributes["style"].split(",")
        assert attributes["penwidth"] == NODE_PENWIDTH == "2"

    @pytest.mark.parametrize("category", ["create", "update", "replace", "delete"])
    def test_no_key_outside_the_decoration_set_is_produced(self, category):
        """Icon, geometry and group can never be touched from here."""
        attributes = node_style_attributes(CHANGE_STYLES[category])

        assert set(attributes) == set(NODE_DECORATION_KEYS)
        for key in ("image", "imagescale", "imagepos", "width", "height", "margin", "fontsize", "labelloc", "group"):
            assert key not in attributes, key

    def test_a_styleless_style_yields_no_attribute(self):
        assert node_style_attributes(CHANGE_STYLES["unchanged"]) == {}
        assert node_style_attributes(resolve_style("unchanged")) == {}
        assert node_style_attributes(resolve_style(None)) == {}

    def test_a_style_without_a_tint_falls_back_to_white(self):
        """A tintless holder still yields a fill, so `filled` is never empty."""
        attributes = node_style_attributes(ChangeStyle(color="#107C10", flag="+", label="Create"))
        assert attributes["fillcolor"] == "white"
        assert set(attributes) == set(NODE_DECORATION_KEYS)

    def test_decoration_keys_are_the_documented_tuple(self):
        assert NODE_DECORATION_KEYS == ("shape", "style", "color", "fillcolor", "penwidth")

    def test_each_category_gets_its_own_border_colour(self):
        borders = {category: node_style_attributes(CHANGE_STYLES[category])["color"] for category in EXPECTED_STYLES}
        assert borders == {category: colour for category, (colour, _flag, _tint) in EXPECTED_STYLES.items()}


class TestLegendLabel:
    """legend_label lists every present category with colour, flag and count."""

    def test_legend_lists_present_categories_in_canonical_order(self):
        label = legend_label(["delete", "create"], {"create": 3, "delete": 2})
        assert label.index("Create") < label.index("Delete")
        assert "Update" not in label
        assert "Replace" not in label

    def test_legend_carries_colour_token_flag_token_and_count(self):
        label = legend_label(["create", "update", "replace", "delete"], {"create": 3, "update": 1, "replace": 1, "delete": 2})
        for category, count in (("create", 3), ("update", 1), ("replace", 1), ("delete", 2)):
            style = CHANGE_STYLES[category]
            assert style.color in label
            assert f"<B>{style.flag}</B>" in label
            assert f"<TD>{count}</TD>" in label

    @pytest.mark.parametrize("category", ["create", "update", "replace", "delete"])
    def test_legend_swatch_mirrors_a_decorated_node(self, category):
        """The swatch is the node decoration: tinted fill, coloured border."""
        style = CHANGE_STYLES[category]
        label = legend_label([category], {category: 1})
        node = node_style_attributes(style)

        assert (
            f"<TD BGCOLOR='{style.tint}' COLOR='{style.color}' BORDER='1' WIDTH='14' HEIGHT='14'></TD>" in label
        )
        # The swatch and the node it stands for read the same two colours.
        assert f"BGCOLOR='{node['fillcolor']}'" in label
        assert f"COLOR='{node['color']}'" in label

    def test_legend_is_a_valid_html_like_label_with_a_title(self):
        label = legend_label(["create"], {"create": 1})
        assert label.startswith("<<TABLE") and label.endswith("</TABLE>>")
        assert LEGEND_TITLE in label

    def test_unchanged_row_is_listed_without_decoration(self):
        label = legend_label(["create", "unchanged"], {"create": 1, "unchanged": 4})
        assert "Unchanged" in label
        assert "<TD></TD><TD>Unchanged</TD><TD>4</TD>" in label

    def test_missing_counts_default_to_zero(self):
        label = legend_label(["delete"], {})
        assert "<TD>0</TD>" in label

    def test_unknown_categories_are_ignored(self):
        label = legend_label(["delete", "obliterate"], {"delete": 1})
        assert "obliterate" not in label
        assert "Delete" in label

    def test_empty_selection_yields_a_title_only_legend(self):
        label = legend_label([], {})
        assert LEGEND_TITLE in label
        assert label.count("<TR>") == 1


class TestChangeStyleHolder:
    """The holder keeps colour, flag, display label and tint together."""

    def test_holder_exposes_its_four_fields(self):
        style = ChangeStyle(color="#107C10", flag="+", label="Create", tint="#DBEBDB")
        assert (style.color, style.flag, style.label, style.tint) == ("#107C10", "+", "Create", "#DBEBDB")

    def test_tint_is_the_only_optional_field(self):
        """`tint` is trailing and optional, so the legacy three-field call works."""
        style = ChangeStyle(color="#107C10", flag="+", label="Create")
        assert style.tint == ""


class TestMirroredModule:
    """The mirrored cloudhorus.utils copy stays in step with utils."""

    def test_tables_and_decoration_match(self):
        from cloudhorus.utils import change_style as mirrored

        def table(module_styles):
            return {
                key: (value.color, value.flag, value.label, value.tint) if value else None
                for key, value in module_styles.items()
            }

        assert table(mirrored.CHANGE_STYLES) == table(CHANGE_STYLES)
        assert mirrored.NODE_DECORATION_KEYS == NODE_DECORATION_KEYS
        assert mirrored.NODE_PENWIDTH == NODE_PENWIDTH

        label = legacy_label("app-web", "sites")
        for category in ("create", "update", "replace", "delete"):
            assert mirrored.decorate_label(label, mirrored.CHANGE_STYLES[category]) == decorate_label(
                label, CHANGE_STYLES[category]
            )
            assert mirrored.node_style_attributes(mirrored.CHANGE_STYLES[category]) == node_style_attributes(
                CHANGE_STYLES[category]
            )
        assert mirrored.legend_label(["create"], {"create": 2}) == legend_label(["create"], {"create": 2})
