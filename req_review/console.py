"""Консольный вывод ReqLens: rich-оформление в терминале и простой текст, если stdout не TTY."""
from __future__ import annotations

import sys

from .pipeline import STEPS

BANNER = "ReqLens · ИИ-ревью требований по ISO/IEC/IEEE 29148"


class Console:
    def __init__(self, quiet: bool = False):
        self.quiet = quiet
        self.rich = None
        if sys.stdout.isatty() and not quiet:
            try:
                from rich.console import Console as RC

                self.rich = RC(highlight=False)
            except ImportError:
                self.rich = None

    # --- поток событий прогона
    def banner(self, input_path: str, label: str, profile: str):
        if self.quiet:
            return
        if self.rich:
            from rich.panel import Panel

            self.rich.print(Panel.fit(f"[bold #4C8DFF]ReqLens[/] · ИИ-ревью требований по ISO/IEC/IEEE 29148\n"
                                      f"[dim]документ:[/] {input_path}   [dim]модель:[/] {label}   [dim]профиль:[/] {profile}",
                                      border_style="#0B5FFF"))
        else:
            print(f"{BANNER}\nдокумент: {input_path} | модель: {label} | профиль: {profile}")

    def step(self, i: int, label: str = ""):
        if self.quiet:
            return
        text = f"[{i + 1}/{len(STEPS)}] {STEPS[i]}" + (f" — {label}" if label else "")
        if self.rich:
            self.rich.print(f"[bold #0B5FFF]●[/] [bold]{text}[/]")
        else:
            print(text, flush=True)

    def log(self, msg: str):
        if self.quiet:
            return
        if self.rich:
            self.rich.print(f"   [dim]{msg}[/]")
        else:
            print("      " + msg, flush=True)

    def error(self, msg: str):
        if self.rich:
            self.rich.print(f"[bold #E5484D]✖ {msg}[/]")
        else:
            print(msg, file=sys.stderr)

    # --- итог
    def summary(self, ctx):
        sc, rv = ctx.scores, ctx.rv
        n_f = sum(len(r.findings) for r in rv.req_results) + len(rv.set_findings)
        n_crit = sum(1 for r in rv.req_results for f in r.findings if f.severity == "critical") + \
            sum(1 for f in rv.set_findings if f.severity == "critical")
        if not self.rich:
            print(f"Готово: требований {len(rv.req_results)}, нарушений {n_f} (критичных {n_crit}), "
                  f"балл {sc.doc_score}/100, готовность {sc.readiness}%, обращений к модели {ctx.llm_stats.calls}, "
                  f"отброшено неподтверждённых цитат {len(rv.dropped)}")
            for name, p in ctx.artifacts.items():
                print(f"  {name}: {p}")
            return
        from rich.table import Table

        color = "#E5484D" if sc.readiness < 50 else "#F59E0B" if sc.readiness < 80 else "#12B76A"
        filled = round(sc.readiness / 100 * 30)
        self.rich.print()
        self.rich.print(f"[bold]Готовность к разработке[/]  [{color}]{'━' * filled}[/][dim]{'━' * (30 - filled)}[/]  "
                        f"[bold {color}]{sc.readiness}%[/]    [bold]Балл документа[/] [bold]{sc.doc_score}[/]/100")
        self.rich.print(f"[dim]требований[/] {len(rv.req_results)}  [dim]нарушений[/] {n_f}  [dim]критичных[/] "
                        f"[#E5484D]{n_crit}[/]  [dim]обращений к модели[/] {ctx.llm_stats.calls}  "
                        f"[dim]отброшено галлюцинаций[/] {len(rv.dropped)}")
        crit = [(rr.req, f) for rr in rv.req_results for f in rr.findings if f.severity == "critical"][:5]
        if crit:
            t = Table(title="Топ критичных дефектов", title_justify="left", border_style="#263042", header_style="bold")
            t.add_column("Требование")
            t.add_column("Критерий")
            t.add_column("Цитата", max_width=60)
            from .criteria import criterion_name

            for r, f in crit:
                t.add_row(r.doc_id or r.rid, criterion_name(f.criterion), f"«{f.quote}»")
            self.rich.print(t)
        self.rich.print("[bold]Артефакты:[/]")
        for name, p in ctx.artifacts.items():
            uri = p.resolve().as_uri()
            self.rich.print(f"  [#4C8DFF]↳[/] {name}: [link={uri}]{p}[/link]")
