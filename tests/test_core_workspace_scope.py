from __future__ import annotations

import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
MAIN_SOURCE = (PROJECT_ROOT / "main.py").read_text(encoding="utf-8")
ALERT_DASHBOARD_SOURCE = (PROJECT_ROOT / "alerts_dashboard.py").read_text(encoding="utf-8")


class CoreWorkspaceScopeTests(unittest.TestCase):
    def test_retired_workspaces_are_not_exposed_in_navigation_or_page_builders(self):
        for label in ("RESEARCH LAB", "STRATEGY LAB", "DATA CENTER", "TICK RESEARCH"):
            self.assertNotIn(label, MAIN_SOURCE)
        for symbol in (
            "research_nav_button", "strategy_nav_button", "data_center_nav_button",
            "_build_research_page", "_build_strategy_page", "_build_data_center_page",
        ):
            self.assertNotIn(symbol, MAIN_SOURCE)

    def test_core_pages_and_standalone_regime_import_remain_available(self):
        for symbol in (
            "sessions_nav_button", "alerts_nav_button", "calendar_nav_button",
            "volatility_nav_button", "regime_nav_button", "focus_nav_button",
            "def import_regime_csv", "REGIME_DATA_PATH",
        ):
            self.assertIn(symbol, MAIN_SOURCE)

    def test_global_session_cards_use_live_analog_and_digital_clocks(self):
        self.assertIn("def _draw_session_analog_clock", MAIN_SOURCE)
        self.assertIn('"analog": analog_canvas', MAIN_SOURCE)
        self.assertIn("self._draw_session_analog_clock(", MAIN_SOURCE)
        self.assertIn('widgets["session_progress"].configure(', MAIN_SOURCE)
        self.assertIn("utc_offset_label(state.local_now)", MAIN_SOURCE)
        self.assertIn("session_window_arc_angles(session, close_at=arc_close)", MAIN_SOURCE)
        self.assertIn('font=("Consolas", 15, "bold")', MAIN_SOURCE)
        self.assertIn('widgets["analog"].configure(bg=palette["panel"])', MAIN_SOURCE)
        self.assertIn('canvas.coords(clock_state["hands"][hand_name]', MAIN_SOURCE)
        self.assertIn('canvas.create_text(', MAIN_SOURCE)
        self.assertIn('text="VELTRIX"', MAIN_SOURCE)
        self.assertIn('"second_counterweight"', MAIN_SOURCE)
        self.assertIn('widgets["card"].configure(', MAIN_SOURCE)

    def test_session_clock_hands_sweep_independently_of_the_status_refresh(self):
        self.assertIn("SESSION_CLOCK_FRAME_MS = 50", MAIN_SOURCE)
        self.assertIn("def _animate_session_clocks", MAIN_SOURCE)
        self.assertIn("SESSION_CLOCK_FRAME_MS, self._animate_session_clocks", MAIN_SOURCE)
        self.assertIn("self.session_animation_job", MAIN_SOURCE)


    def test_global_session_intelligence_uses_the_session_engine_and_scrollable_map(self):
        self.assertIn("from session_timeline import build_session_timeline", MAIN_SOURCE)
        self.assertIn("def _build_session_timeline", MAIN_SOURCE)
        self.assertIn("def _draw_session_timeline", MAIN_SOURCE)
        self.assertIn("build_session_timeline(", MAIN_SOURCE)
        self.assertIn("apply_exchange_calendar=self.exchange_calendar_enabled_var.get()", MAIN_SOURCE)
        self.assertIn("self._draw_session_timeline(now_utc, states)", MAIN_SOURCE)
        self.assertIn("self.sessions_canvas", MAIN_SOURCE)
        self.assertIn("def _draw_world_session_dial", MAIN_SOURCE)
        self.assertIn('self.session_timeline_canvas.bind("<Button-1>"', MAIN_SOURCE)
        self.assertIn('self.session_timeline_canvas.bind("<B1-Motion>"', MAIN_SOURCE)
        self.assertIn("def _probe_session_timeline", MAIN_SOURCE)
        self.assertIn("timeline_probe_from_x(event.x", MAIN_SOURCE)

    def test_market_session_intelligence_and_profiles_are_wired_into_global_sessions(self):
        for symbol in (
            "from session_intelligence import historical_overlap_report, weekly_session_hours",
            "from session_profiles import PROFILE_NAMES",
            "def _apply_selected_session_profile",
            "def edit_custom_session_profile",
            "def _refresh_session_intelligence",
            "WEEKLY SCHEDULED HOURS · LOCAL MON–SUN",
            "PAST {period}D",
            "EDIT CUSTOM",
        ):
            self.assertIn(symbol, MAIN_SOURCE)

    def test_cash_exchange_calendar_overlay_is_optional_and_wired_into_clocks_alerts_and_timeline(self):
        for symbol in (
            "from exchange_calendar import EXCHANGE_CALENDARS, get_exchange_aware_session_state, upcoming_exchange_events",
            "CASH EXCHANGE HOLIDAYS / EARLY CLOSES",
            "def _toggle_exchange_calendar",
            "def _update_exchange_calendar_summary",
            "get_exchange_aware_session_state(",
            "apply_exchange_calendar=self.exchange_calendar_enabled_var.get()",
            "EXCHANGE_HOLIDAY",
            "CLOSING_PROCESS",
        ):
            self.assertIn(symbol, MAIN_SOURCE)

    def test_session_risk_awareness_is_wired_into_cards_alerts_and_preferences(self):
        for symbol in (
            "from risk_engine import assess_session_risk, due_session_risk_alerts",
            "SESSION-SPECIFIC REMINDER OVERRIDES",
            "SESSION RISK AWARENESS",
            "def _poll_session_risk_alerts",
            "SESSION RISK · {assessment.level}",
            "CLOSING CAUTION MIN",
            "risk_alerted_keys",
        ):
            self.assertIn(symbol, MAIN_SOURCE)

    def test_alerts_workspace_uses_screenshot_inspired_market_watch_layout(self):
        for symbol in (
            "from alerts_dashboard import",
            "def _build_alerts_page",
            "build_alerts_dashboard(self, self.alerts_content)",
            "refresh_alerts_dashboard(self, now_utc, states)",
            "toggle_alert_settings(self)",
            "apply_alerts_tree_theme(self)",
        ):
            self.assertIn(symbol, MAIN_SOURCE)
        for symbol in (
            "MARKET WATCH · TRADING HOURS",
            "GLOBAL SESSION MAP · UTC 00:00–24:00",
            "CURRENT SESSION",
            "SYMBOL WATCHLIST · 28 MAJOR / CROSS FX PAIRS",
            "NEWS CALENDAR · HIGH / MEDIUM IMPACT",
            "REFERENCE SCHEDULE ONLY",
            "ALERT RULES / PREFERENCES",
        ):
            self.assertIn(symbol, ALERT_DASHBOARD_SOURCE)

    def test_removed_research_and_execution_engines_are_not_imported_by_main(self):
        for module in ("research_engine", "backtest_engine", "bar_engine", "data_gateway"):
            self.assertNotIn(f"import {module}", MAIN_SOURCE)
            self.assertNotIn(f"from {module}", MAIN_SOURCE)


if __name__ == "__main__":
    unittest.main()
