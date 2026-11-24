import unittest
from unittest.mock import Mock

from themes import THEMES
from ui_theme import (
    COMBOBOX_STYLES,
    TREEVIEW_STYLES,
    apply_veltrix_classic_widget_palette,
    apply_veltrix_font_defaults,
    apply_veltrix_ttk_palette,
    prepare_veltrix_ttk_theme,
)


class FakeWidget:
    def __init__(self, name, widget_class="Frame", master=None, children=None):
        self.name = name
        self.widget_class = widget_class
        self.master = master
        self.children = list(children or [])
        self.options = {}
        for child in self.children:
            child.master = self

    def __str__(self):
        return self.name

    def winfo_children(self):
        return self.children

    def winfo_class(self):
        return self.widget_class

    def cget(self, option):
        aliases = {"background": "bg"}
        return self.options.get(aliases.get(option, option), "")

    def configure(self, **kwargs):
        self.options.update(kwargs)


class VeltrixTtkThemeTests(unittest.TestCase):
    def test_prefers_clam_when_available(self):
        style = Mock()
        style.theme_names.return_value = ("vista", "clam", "default")
        style.theme_use.side_effect = ["clam", "clam"]

        selected = prepare_veltrix_ttk_theme(style)

        self.assertEqual(selected, "clam")
        style.theme_use.assert_any_call("clam")

    def test_keeps_platform_theme_when_clam_is_unavailable(self):
        style = Mock()
        style.theme_names.return_value = ("vista", "default")
        style.theme_use.return_value = "vista"

        selected = prepare_veltrix_ttk_theme(style)

        self.assertEqual(selected, "vista")
        style.theme_use.assert_called_once_with()

    def test_ttk_palette_covers_global_controls_and_all_treeview_styles(self):
        style = Mock()
        root = Mock()
        palette = THEMES["MATRIX"]

        apply_veltrix_ttk_palette(style, palette, root)

        configured_names = [call.args[0] for call in style.configure.call_args_list]
        mapped_names = [call.args[0] for call in style.map.call_args_list]
        for required in (".", "TFrame", "TLabel", "TButton", "TEntry", "TSpinbox",
                         "TCheckbutton", "TRadiobutton", "TLabelframe", "TNotebook",
                         "TNotebook.Tab", "TScrollbar", *COMBOBOX_STYLES, *TREEVIEW_STYLES):
            self.assertIn(required, configured_names)
        for tree_style in TREEVIEW_STYLES:
            self.assertIn(f"{tree_style}.Heading", configured_names)
            self.assertIn(tree_style, mapped_names)
        for combo_style in COMBOBOX_STYLES:
            self.assertIn(combo_style, mapped_names)
        tree_config = next(call for call in style.configure.call_args_list
                           if call.args[0] == "Veltrix.Regime.Treeview")
        heading_config = next(call for call in style.configure.call_args_list
                              if call.args[0] == "Veltrix.Regime.Treeview.Heading")
        self.assertEqual(tree_config.kwargs["fieldbackground"], palette["bg"])
        self.assertEqual(tree_config.kwargs["font"], ("Segoe UI", 9))
        self.assertEqual(tree_config.kwargs["rowheight"], 29)
        self.assertEqual(heading_config.kwargs["background"], palette["panel"])
        self.assertEqual(heading_config.kwargs["font"], ("Segoe UI", 9, "bold"))
        self.assertEqual(root.option_add.call_count, 50)

    def test_native_widget_font_defaults_use_segoe_ui(self):
        root = Mock()

        apply_veltrix_font_defaults(root)

        options = {call.args[0]: call.args[1] for call in root.option_add.call_args_list}
        self.assertEqual(options["*Font"], ("Segoe UI", 10))
        self.assertEqual(options["*Label.font"], ("Segoe UI", 10))
        self.assertEqual(options["*Button.font"], ("Segoe UI", 10, "bold"))
        self.assertEqual(options["*Entry.font"], ("Segoe UI", 10))
        self.assertGreaterEqual(len(options), 10)

    def test_palette_switch_updates_all_global_selection_styles(self):
        style = Mock()
        root = Mock()
        for theme_name in ("CYAN", "AMBER", "MATRIX", "VIOLET", "ICE", "LIGHT"):
            apply_veltrix_ttk_palette(style, THEMES[theme_name], root)

        self.assertEqual(style.configure.call_count, 6 * 27)
        self.assertEqual(style.map.call_count, 6 * 18)
        self.assertEqual(root.option_add.call_count, 50 * len(THEMES))

    def test_missing_dropdown_option_database_does_not_crash(self):
        style = Mock()
        root = Mock()
        root.option_add.side_effect = RuntimeError("unsupported option database")

        apply_veltrix_ttk_palette(style, THEMES["CYAN"], root)

        self.assertEqual(root.option_add.call_count, 50)

    def test_classic_widget_pass_themes_unregistered_controls_recursively(self):
        button = FakeWidget(".root.panel.button", "Button")
        entry = FakeWidget(".root.panel.entry", "Entry")
        label = FakeWidget(".root.panel.label", "Label")
        listbox = FakeWidget(".root.panel.list", "Listbox")
        menu = FakeWidget(".root.panel.menu", "Menu")
        panel = FakeWidget(".root.panel", "Frame", children=[button, entry, label, listbox, menu])
        root = FakeWidget(".root", "Tk", children=[panel])
        palette = THEMES["VIOLET"]
        panel.configure(bg=palette["panel"])

        apply_veltrix_classic_widget_palette(root, palette, registered_widgets=[panel])

        self.assertEqual(button.options["bg"], palette["button_bg"])
        self.assertEqual(button.options["activebackground"], palette["button_active"])
        self.assertEqual(entry.options["bg"], palette["entry_bg"])
        self.assertEqual(entry.options["highlightthickness"], 0)
        self.assertEqual(entry.options["insertbackground"], palette["bright"])
        self.assertEqual(label.options["bg"], palette["panel"])
        self.assertEqual(listbox.options["selectbackground"], palette["button_active"])
        self.assertEqual(menu.options["bg"], palette["panel"])

    def test_classic_widget_pass_preserves_registered_semantic_surfaces(self):
        button = FakeWidget(".root.panel.button", "Button")
        panel = FakeWidget(".root.panel", "Frame", children=[button])
        root = FakeWidget(".root", "Tk", children=[panel])
        palette = THEMES["AMBER"]
        panel.configure(bg=palette["panel"])

        apply_veltrix_classic_widget_palette(root, palette, registered_widgets=[panel])

        self.assertEqual(panel.options["bg"], palette["panel"])
        self.assertEqual(button.options["bg"], palette["button_bg"])

    def test_entry_and_spinbox_receive_only_supported_widget_options(self):
        class StrictControl(FakeWidget):
            def configure(self, **kwargs):
                allowed = {
                    "bg", "fg", "insertbackground", "selectbackground", "selectforeground",
                    "highlightbackground", "highlightcolor", "highlightthickness", "disabledbackground",
                    "disabledforeground", "buttonbackground",
                }
                unsupported = set(kwargs) - allowed
                if unsupported:
                    raise RuntimeError(f"unsupported options: {sorted(unsupported)}")
                self.options.update(kwargs)

        palette = THEMES["CYAN"]
        entry = StrictControl(".root.entry", "Entry")
        spinbox = StrictControl(".root.spinbox", "Spinbox")
        root = FakeWidget(".root", "Tk", children=[entry, spinbox])

        apply_veltrix_classic_widget_palette(root, palette)

        self.assertEqual(entry.options["bg"], palette["entry_bg"])
        self.assertNotIn("buttonbackground", entry.options)
        self.assertEqual(spinbox.options["bg"], palette["entry_bg"])
        self.assertEqual(spinbox.options["buttonbackground"], palette["button_bg"])

    def test_classic_widget_pass_handles_widget_configuration_errors(self):
        broken = Mock()
        broken.__str__ = Mock(return_value=".root.broken")
        broken.winfo_class.return_value = "Button"
        broken.winfo_children.return_value = []
        broken.configure.side_effect = RuntimeError("cannot configure this widget")
        root = Mock()
        root.winfo_children.return_value = [broken]

        apply_veltrix_classic_widget_palette(root, THEMES["CYAN"])

        broken.configure.assert_called_once()


if __name__ == "__main__":
    unittest.main()
