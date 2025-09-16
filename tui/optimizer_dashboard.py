import json
import glob
import time
from pathlib import Path
from rich.text import Text
from rich.panel import Panel
from datetime import datetime
import psutil
from decimal import Decimal, InvalidOperation

from textual.app import App, ComposeResult
from textual.widgets import Header, Footer, Static, Log, DataTable
from textual.containers import Container, Vertical, ScrollableContainer
from textual.timer import Timer

# Directory where the optimizer drops its progress files
TUI_FILES_DIR = Path(".tui_files")

class ComparisonWidget(Container):
    """A widget to display a side-by-side comparison of a backtest result."""

    def __init__(self, title: str, **kwargs):
        super().__init__(**kwargs)
        self.title_text = title
        self.baseline_summary = {} # Store baseline data for comparison

    def compose(self) -> ComposeResult:
        """Compose the widget's layout."""
        with Container(classes="main_container"):
            yield Static(self.title_text, classes="widget_title")
            with Container(classes="table_container"):
                yield DataTable(id="metrics_table", classes="summary_table")
                yield DataTable(id="params_table", classes="params_table")

    def on_mount(self) -> None:
        """Called when the widget is mounted to set up tables."""
        metrics_table = self.query_one("#metrics_table", DataTable)
        metrics_table.add_column("Metric", width=25)
        metrics_table.add_column("Value", width=20)
        metrics_table.add_column("Improvement", width=20) # New column
        metrics_table.add_row("[dim]Waiting for data...[/dim]", "", "")

        params_table = self.query_one("#params_table", DataTable)
        params_table.add_column("Parameter", width=30)
        params_table.add_column("Value", width=25)
        params_table.add_row("[dim]Waiting for data...[/dim]", "")

    def update_data(self, data: dict, baseline_data: dict = None):
        """Updates the widget's tables with new data."""
        if not data:
            return

        is_baseline = baseline_data is None
        self.baseline_summary = baseline_data.get("summary", baseline_data) if baseline_data else {}

        summary = data.get("summary", data)
        params = data.get("params")

        # === Update Metrics Table ===
        metrics_table = self.query_one("#metrics_table", DataTable)
        metrics_table.clear()
        metrics_table.add_column("Metric", width=25)
        metrics_table.add_column("Value", width=20)
        metrics_table.add_column("Improvement", width=20)

        key_metrics = {
            "final_balance": ("Final Balance", "money"),
            "net_pnl_pct": ("Net PnL %", "percent"),
            "win_rate": ("Win Rate", "percent"),
            "profit_factor": ("Profit Factor", "ratio"),
            "max_drawdown": ("Max Drawdown %", "percent_dd"),
            "sharpe_ratio": ("Sharpe Ratio", "ratio"),
            "sortino_ratio": ("Sortino Ratio", "ratio"),
            "sell_trades_count": ("Sell Trades", "integer"),
        }

        for key, (name, metric_type) in key_metrics.items():
            value = summary.get(key)
            value_str = self._format_metric(value, metric_type)

            improvement_str = ""
            if not is_baseline and self.baseline_summary:
                baseline_value = self.baseline_summary.get(key)
                improvement_str = self._calculate_improvement(value, baseline_value, metric_type)

            metrics_table.add_row(name, value_str, improvement_str)

        if "score" in data:
            metrics_table.add_row("Score", f"{data['score']:.4f}", "")
        if "trial_number" in data:
            metrics_table.add_row("Trial #", str(data['trial_number']), "")

        # === Update Parameters Table ===
        params_table = self.query_one("#params_table", DataTable)
        params_table.clear()
        params_table.add_column("Parameter", width=30)
        params_table.add_column("Value", width=25)

        if not params:
            params_table.add_row("[dim]Not applicable.[/dim]", "")
        else:
            original_params = self.baseline_summary.get("params") if self.baseline_summary else (baseline_data.get("params") if baseline_data else None)

            for key, value in sorted(params.items()):
                value_str = f"{value:.6f}" if isinstance(value, float) else str(value)

                if not is_baseline and original_params and str(original_params.get(key)) != str(value):
                    key_str = f"[bold yellow]{key}[/bold yellow]"
                    value_str = f"[bold yellow]{value_str}[/bold yellow]"
                else:
                    key_str = key

                params_table.add_row(key_str, value_str)

    def _format_metric(self, value, metric_type):
        if value is None: return "[dim]N/A[/dim]"
        try:
            val = Decimal(str(value))
            if metric_type == "money": return f"${val:,.2f}"
            if metric_type == "percent": return f"{val:.2%}"
            if metric_type == "percent_dd": return f"{val * 100:.2f}%"
            if metric_type == "ratio": return f"{val:.2f}"
            if metric_type == "integer": return str(int(val))
            return str(value)
        except (InvalidOperation, TypeError):
            return str(value)

    def _calculate_improvement(self, current_val, baseline_val, metric_type):
        if current_val is None or baseline_val is None: return ""
        try:
            current = Decimal(str(current_val))
            baseline = Decimal(str(baseline_val))

            if baseline == 0 and current > 0: return "[bold green]∞[/]"
            if baseline == 0: return ""

            delta = current - baseline

            # Invert delta for drawdown, since lower is better
            if metric_type == "percent_dd":
                delta = -delta

            style = "bold green" if delta > 0 else "bold red" if delta < 0 else "dim"

            if metric_type in ["percent", "percent_dd"]:
                return f"[{style}]{delta:+.2%}[/{style}]"
            if metric_type in ["money", "ratio"]:
                return f"[{style}]{delta:+,.2f}[/{style}]"
            if metric_type == "integer":
                 return f"[{style}]{int(delta):+d}[/{style}]"
            return ""
        except (InvalidOperation, TypeError):
            return ""


class OptimizerDashboard(App):
    CSS = """
    Screen { background: $surface; }
    #main_container { padding: 0 1; width: 100%; height: 100%; layout: horizontal; grid-size: 2; grid-gutter: 1; }
    .main_container { border: round white; padding: 0 1; }
    .widget_title { width: 100%; text-align: center; padding-top: 1; text-style: bold; }
    .table_container { layout: vertical; height: 100%; padding-top: 1; }
    .summary_table { height: 12; margin-bottom: 1; }
    .params_table { height: 100%; }
    #status_bar { dock: top; height: 3; content-align: center middle; background: $panel; border: round white; }
    #trial_log_container { height: 24; border: heavy white; padding: 1; margin: 1 0; }
    .log_header { width: 100%; text-align: center; text-style: bold; }
    .log_box { height: 100%; border: none; }
    """
    BINDINGS = [("q", "quit", "Quit")]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.update_timer: Timer = None
        self.processed_trial_files = set()
        self.baseline_data = {}
        self.best_trial_data = {}
        self.optimizer_process_found = False

    def compose(self) -> ComposeResult:
        yield Header(name="⚡ Genius Optimizer Dashboard ⚡")
        yield Static("⚪ Waiting for optimization to begin...", id="status_bar")
        with ScrollableContainer():
            with Container(id="main_container"):
                yield ComparisonWidget(title="📊 Baseline (.env)", id="baseline_widget")
                yield ComparisonWidget(title="🏆 Best Performer", id="best_performer_widget")
            yield Vertical(
                Static("Live Trial Log", classes="log_header"),
                Log(id="live_trial_log", auto_scroll=True, classes="log_box"),
                id="trial_log_container"
            )
        yield Footer()

    def on_mount(self) -> None:
        TUI_FILES_DIR.mkdir(exist_ok=True)
        self.update_timer = self.set_interval(1.5, self.update_dashboard)

    def _is_optimizer_running(self) -> bool:
        try:
            for p in psutil.process_iter(['name', 'cmdline']):
                if p.info['cmdline'] and 'run_genius_optimizer.py' in ' '.join(p.info['cmdline']):
                    self.optimizer_process_found = True
                    return True
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            pass
        return False

    def update_dashboard(self) -> None:
        status_bar = self.query_one("#status_bar", Static)
        is_running = self._is_optimizer_running()
        if is_running:
             status_bar.update("⚡ OPTIMIZING... ⚡")
        elif self.optimizer_process_found and not is_running:
            status_bar.update("✅ OPTIMIZATION COMPLETED ✅")
        else:
            status_bar.update("⚪ Waiting for optimization to begin...")

        if not self.baseline_data:
            baseline_file = TUI_FILES_DIR / "baseline_summary.json"
            if baseline_file.exists():
                try:
                    with open(baseline_file, "r") as f:
                        self.baseline_data = json.load(f)
                    baseline_widget = self.query_one("#baseline_widget", ComparisonWidget)
                    baseline_widget.update_data(self.baseline_data)
                except (json.JSONDecodeError, IOError, KeyError) as e:
                    self.log(f"Error processing baseline file: {e}")

        best_trial_file = TUI_FILES_DIR / "best_overall_trial.json"
        if best_trial_file.exists():
            try:
                with open(best_trial_file, "r") as f:
                    new_data = json.load(f)
                if new_data.get("trial_number") != self.best_trial_data.get("trial_number"):
                    self.best_trial_data = new_data
                    best_performer_widget = self.query_one("#best_performer_widget", ComparisonWidget)
                    best_performer_widget.update_data(self.best_trial_data, self.baseline_data)
            except (json.JSONDecodeError, IOError, KeyError) as e:
                self.log(f"Error processing best trial file: {e}")

        trial_files = glob.glob(str(TUI_FILES_DIR / "genius_trial_*.json"))
        new_trial_files = sorted([f for f in trial_files if f not in self.processed_trial_files])

        trial_log = self.query_one("#live_trial_log", Log)
        for file_path in new_trial_files:
            self.processed_trial_files.add(file_path)
            try:
                with open(file_path, "r") as f:
                    data = json.load(f)

                summary = data.get("summary", {})
                score = data.get('score', 0) or 0.0
                balance = summary.get('final_balance', 0)
                pnl_pct = summary.get('net_pnl_pct', 0)
                regime = data.get("regime", -1)
                trial_num = data.get('number', -1)
                params_str = ", ".join([f"{k.split('_')[-1]}={v:.3f}" if isinstance(v, float) else f"{k.split('_')[-1]}={v}" for k, v in data.get("params", {}).items()])

                log_line = (
                    f"[{datetime.now():%H:%M:%S}] [b]Regime {regime} | Trial {trial_num}[/b]\n"
                    f"  - [b]Score[/b]: {score:10.4f} | [b]Balance[/b]: ${float(balance):,.2f} | [b]PnL%[/b]: {float(pnl_pct):.2%}\n"
                    f"  - [b]Params[/b]: [dim]({params_str})[/dim]\n"
                )
                trial_log.write(log_line)

            except (json.JSONDecodeError, IOError, KeyError) as e:
                trial_log.write(f"[{datetime.now():%H:%M:%S}] Error processing file {Path(file_path).name}: {e}")
                continue

if __name__ == "__main__":
    app = OptimizerDashboard()
    app.run()
