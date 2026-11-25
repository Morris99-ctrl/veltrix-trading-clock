from __future__ import annotations

import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
MAIN_SOURCE = (PROJECT_ROOT / "main.py").read_text(encoding="utf-8")
ALERT_DASHBOARD_SOURCE = (PROJECT_ROOT / "alerts_dashboard.py").read_text(encoding="utf-8")
SESSION_PERFORMANCE_SOURCE = (PROJECT_ROOT / "session_performance.py").read_text(encoding="utf-8")
SESSION_PERFORMANCE_UI_SOURCE = (PROJECT_ROOT / "session_performance_ui.py").read_text(encoding="utf-8")


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

    def test_command_center_is_default_landing_workspace_and_reuses_existing_workspaces(self):
        for symbol in (
            "command_center_nav_button", "command_center_view",
            'self.show_page("command_center")',
            "build_command_center_page(self)", "refresh_command_center(self, now_utc)",
            "apply_command_center_theme(self)",
        ):
            self.assertIn(symbol, MAIN_SOURCE)
        command_engine = (PROJECT_ROOT / "command_center_engine.py").read_text(encoding="utf-8")
        command_ui = (PROJECT_ROOT / "command_center_ui.py").read_text(encoding="utf-8")
        for symbol in (
            "build_command_center_snapshot", "assess_session_risk",
            "event_count_next_24h", "market_is_fresh", "calendar_is_fresh",
        ):
            self.assertIn(symbol, command_engine)
        for symbol in (
            "refresh_live_calendar(silent=False)", "refresh_market_data(silent=False)",
            "daily_checklists", "PRE-MARKET PREPARATION",
            "GLOBAL SESSION STATUS", "UPCOMING ECONOMIC EVENTS",
            "VOLATILITY & MARKET SNAPSHOT", "RISK & ATTENTION",
        ):
            self.assertIn(symbol, command_ui)

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
        self.assertIn("SESSION_CLOCK_FRAME_MS = 16", MAIN_SOURCE)
        self.assertIn("SESSION_CLOCK_RING_REFRESH_SECONDS = 0.25", MAIN_SOURCE)
        self.assertIn("session_clock_hand_polygon_coordinates", MAIN_SOURCE)
        self.assertIn("def _animate_session_clocks", MAIN_SOURCE)
        self.assertIn("SESSION_CLOCK_FRAME_MS, self._animate_session_clocks", MAIN_SOURCE)
        self.assertIn("self.session_animation_job", MAIN_SOURCE)


    def test_hidden_dashboards_skip_periodic_rendering_and_refresh_when_opened(self):
        self.assertIn('if self.current_page == "alerts":\n            refresh_alerts_dashboard', MAIN_SOURCE)
        self.assertIn('if self.current_page == "alerts":\n            refresh_alert_center', MAIN_SOURCE)
        self.assertIn('if self.current_page == "command_center":\n            refresh_command_center', MAIN_SOURCE)
        self.assertIn('if page == "alerts":', MAIN_SOURCE)
        self.assertIn('elif page == "command_center":', MAIN_SOURCE)

    def test_session_clock_animation_pauses_outside_the_sessions_workspace(self):
        self.assertIn('if self.current_page != "sessions":', MAIN_SOURCE)
        self.assertIn('self.session_animation_job = None', MAIN_SOURCE)
        self.assertIn('page == "sessions" and self.session_animation_job is None', MAIN_SOURCE)
        self.assertIn('SESSION_CLOCK_FRAME_MS, self._animate_session_clocks', MAIN_SOURCE)

    def test_hidden_global_sessions_render_only_when_active(self):
        self.assertIn('if self.current_page == "sessions":\n            self._refresh_global_sessions_workspace', MAIN_SOURCE)
        self.assertIn('def _refresh_global_sessions_workspace(', MAIN_SOURCE)
        self.assertIn('elif page == "sessions":', MAIN_SOURCE)
        self.assertIn('self._refresh_global_sessions_workspace(\n                now_utc, states, exchange_calendar_enabled', MAIN_SOURCE)
        self.assertIn('self._draw_session_timeline(now_utc, states)', MAIN_SOURCE)
        self.assertIn('self._refresh_session_intelligence(now_utc)', MAIN_SOURCE)

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
        ):
            self.assertIn(symbol, ALERT_DASHBOARD_SOURCE)
        self.assertIn("ALERT RULES / PREFERENCES", MAIN_SOURCE)

    def test_session_performance_workspace_reuses_local_ohlc_datasets(self):
        for symbol in (
            "from session_performance import analyse_session_performance",
            "from session_performance_ui import",
            "session_performance_view",
            "def run_session_performance",
            "def _drain_session_performance_results",
            "def export_session_performance",
            "refresh_session_performance_dataset_choices(self)",
        ):
            self.assertIn(symbol, MAIN_SOURCE)
        for symbol in (
            "SESSION PERFORMANCE INTELLIGENCE",
            "LOCAL OHLC DATASET (SHARED WITH REGIME LAB)",
            "RUN SESSION STUDY",
            "EXPORT DAILY CSV",
        ):
            self.assertIn(symbol, SESSION_PERFORMANCE_UI_SOURCE)
        for symbol in (
            "bar_interval_minutes",
            "minimum_coverage_pct",
            "positive_rate_pct",
            "overlap_groups",
            "classification_uses_future_data",
            "bar-open timestamp",
        ):
            self.assertIn(symbol, SESSION_PERFORMANCE_SOURCE)

    def test_session_performance_v10_10_rolling_rankings_and_causal_regime_breakdown(self):
        for symbol in (
            "rolling_window_sessions=rolling_window",
            "ranking_min_samples=ranking_minimum",
            "regime_labels=causal_labels",
            "minimum_regime_coverage_pct=minimum_regime_coverage",
            "analyse_market_regimes(bars, regime_config)",
            "Forward-return outcomes produced for the Regime Lab display are ignored.",
        ):
            self.assertIn(symbol, MAIN_SOURCE)
        for symbol in (
            "ROLLING SESSION RANKING",
            "SESSION RESULTS BY DOMINANT CAUSAL MARKET REGIME",
            "MIN SAMPLE TO RANK",
            "MIN REGIME COVERAGE",
            "rolling_compounded_return_pct",
            "rolling_max_drawdown_pct",
            "consistency_score",
        ):
            self.assertIn(symbol, SESSION_PERFORMANCE_UI_SOURCE)
        for symbol in (
            "def _attach_rolling_metrics",
            "def _dominant_regime",
            "def _equity_path_metrics",
            "rolling_window_sessions",
            "regime_breakdown",
            "Forward-return outcomes from Regime Lab are never consulted.",
        ):
            self.assertIn(symbol, SESSION_PERFORMANCE_SOURCE)

    def test_removed_research_and_execution_engines_are_not_imported_by_main(self):
        for module in ("research_engine", "backtest_engine", "bar_engine", "data_gateway"):
            self.assertNotIn(f"import {module}", MAIN_SOURCE)
            self.assertNotIn(f"from {module}", MAIN_SOURCE)


if __name__ == "__main__":
    unittest.main()
