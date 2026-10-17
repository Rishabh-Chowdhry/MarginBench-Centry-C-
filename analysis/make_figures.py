"""Stage-4 analysis: tables (results/processed/summary.md) and figures (figures/*.png)
from results/raw/*.jsonl. Every number in the Stage-4 document comes from here.

Run: python3 -I analysis/make_figures.py
"""

import json
import math
import pathlib
import sys
from collections import defaultdict

import numpy as np

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import matplotlib  # noqa: E402

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import matplotlib.ticker  # noqa: E402

from analysis.stats import (bootstrap_ci, bootstrap_ratio_ci, censor, holm, kaplan_meier,  # noqa: E402
                            mann_whitney, wilson)
from experiments.common import RAW, load  # noqa: E402
from experiments.configs import HORIZON  # noqa: E402

FIG = ROOT / "figures"
OUT = ROOT / "results" / "processed"
EPS = 0.05

# validated categorical palette (dataviz reference instance, light mode), fixed order
SURFACE, INK, INK2, GRID = "#fcfcfb", "#0b0b0b", "#52514e", "#e4e3df"
COLORS = {"FRESCO (cooperative)": "#2a78d6", "independent eps/W": "#eb6834", "centralized scheduler": "#1baf7a"}
SERIES = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100"]
METHOD_ORDER = list(COLORS)

plt.rcParams.update({
    "figure.facecolor": SURFACE, "axes.facecolor": SURFACE, "savefig.facecolor": SURFACE,
    "axes.edgecolor": GRID, "axes.labelcolor": INK2, "xtick.color": INK2, "ytick.color": INK2,
    "text.color": INK, "axes.grid": True, "grid.color": GRID, "grid.linewidth": 0.8,
    "axes.spines.top": False, "axes.spines.right": False, "font.size": 9,
    "axes.titlesize": 10, "axes.titleweight": "bold", "legend.frameon": False,
    "lines.linewidth": 2, "lines.solid_capstyle": "round",
})
MK = dict(marker="o", markersize=6, markeredgecolor=SURFACE, markeredgewidth=1.5)

md = []


def table(header, rows):
    md.append("| " + " | ".join(header) + " |")
    md.append("|" + "---|" * len(header))
    for r in rows:
        md.append("| " + " | ".join(str(x) for x in r) + " |")
    md.append("")


def fmt_ci(t, digits=0):
    v, lo, hi = t
    f = f"{{:,.{digits}f}}"
    return f"{f.format(v)} [{f.format(lo)}, {f.format(hi)}]"


def have(name):
    return (RAW / f"{name}.jsonl").exists()


def end_label(ax, x, y, text, color):
    ax.annotate(text, (x, y), xytext=(6, 0), textcoords="offset points", va="center",
                fontsize=8, color=INK2)


def end_labels_log(ax, items, min_gap=0.12):
    """Direct labels at line ends on a log-y axis, nudged apart so they never overlap.
    items: [(x, y, text)]; min_gap in decades."""
    items = sorted(items, key=lambda t: t[1])
    placed = []
    for x, y, text in items:
        ly = math.log10(y)
        if placed and ly - placed[-1] < min_gap:
            ly = placed[-1] + min_gap
        placed.append(ly)
        ax.annotate(text, (x, y), xytext=(x * 1.12, 10 ** ly), textcoords="data", va="center",
                    fontsize=8, color=INK2)


# ------------------------------------------------------------------ E2 / E3
def reached(r):
    return r.get("b_hat") is not None and r["b_hat"] <= r["k_star"] and r.get("time_final_frontier") is not None


def times_calls(rows):
    t = [r["time_final_frontier"] if reached(r) else None for r in rows]
    tv, te = censor(t, HORIZON)
    calls = np.array([r["calls_until_final"] if reached(r) else r["slots_leased"] for r in rows], float)
    return tv, te, calls


def e2():
    rows = load("e2_scaling")
    groups = defaultdict(list)
    for r in rows:
        groups[(r["exp"], r["scenario"], r["method"], r["W"])].append(r)
    scen = sorted({k[1] for k in groups if k[0] == "strong"})
    md.append("## E2/E3 — strong scaling and H-coop\n")
    md.append(f"Time-to-target is censored at the horizon H = {HORIZON:,.0f} s (virtual). "
              "RMST = restricted mean of min(T, H). Calls are counted up to reaching the target, "
              "or all calls by H if censored. 95% bootstrap CIs.\n")
    summary = {}
    for sc in scen:
        md.append(f"### {sc}\n")
        out = []
        for m in METHOD_ORDER:
            for W in sorted({k[3] for k in groups if k[1] == sc}):
                g = groups.get(("strong", sc, m, W)) or (groups.get(("strong", sc, METHOD_ORDER[0], 1)) if W == 1 else None)
                if not g:
                    continue
                tv, te, calls = times_calls(g)
                rm = bootstrap_ci(tv)
                cm = bootstrap_ci(calls)
                p, lo, hi = wilson(int(te.sum()), len(te))
                summary[(sc, m, W)] = (tv, te, calls, rm, cm)
                out.append([m, W, len(g), f"{p:.2f} [{lo:.2f}, {hi:.2f}]", fmt_ci(rm), fmt_ci(cm),
                            f"{np.median(tv):,.0f}"])
        table(["method", "W", "runs", "P(reach k* by H)", "RMST time (s)", "mean calls", "median time (s)"], out)
    # H-coop tests
    md.append("### H-coop tests (two-sided Mann-Whitney on censored time; Holm over all 20 comparisons)\n")
    tests = []
    for sc in scen:
        for W in (2, 4, 8, 16, 32):
            for other in ("independent eps/W", "centralized scheduler"):
                if (sc, other, W) not in summary:
                    continue
                a = summary[(sc, METHOD_ORDER[0], W)]
                b = summary[(sc, other, W)]
                _, p, rbc = mann_whitney(a[0], b[0])
                ratio = bootstrap_ratio_ci(a[0], b[0])
                cratio = bootstrap_ratio_ci(a[2], b[2])
                tests.append([sc, W, other, ratio, cratio, rbc, p])
    if tests:
        adj = holm([t[-1] for t in tests])
        table(["scenario", "W", "FRESCO vs", "RMST time ratio (FRESCO/other)", "calls ratio", "rank-biserial",
               "p (raw)", "p (Holm)", "verdict (Holm < 0.05)"],
              [[t[0], t[1], t[2], f"{t[3][0]:.2f} [{t[3][1]:.2f}, {t[3][2]:.2f}]",
                f"{t[4][0]:.2f} [{t[4][1]:.2f}, {t[4][2]:.2f}]", f"{t[5]:+.2f}", f"{t[6]:.3g}", f"{a:.3g}",
                ("FRESCO faster" if t[3][0] < 1 else "FRESCO slower") if a < 0.05 else "no detected difference"]
               for t, a in zip(tests, adj)])

    # Figure 1: strong scaling RMST time vs W
    fig, axes = plt.subplots(1, len(scen), figsize=(4.2 * len(scen), 3.4), sharey=True)
    axes = np.atleast_1d(axes)
    for ax, sc in zip(axes, scen):
        ends = []
        for m in METHOD_ORDER:
            Ws = [W for W in (1, 2, 4, 8, 16, 32) if (sc, m, W) in summary or (W == 1 and (sc, METHOD_ORDER[0], 1) in summary)]
            ys, lo, hi = [], [], []
            for W in Ws:
                s = summary.get((sc, m, W)) or summary[(sc, METHOD_ORDER[0], 1)]
                ys.append(s[3][0]); lo.append(s[3][1]); hi.append(s[3][2])
            ax.fill_between(Ws, lo, hi, color=COLORS[m], alpha=0.10, linewidth=0)
            ax.plot(Ws, ys, color=COLORS[m], label=m, **MK)
            ends.append((Ws[-1], ys[-1], m.split(" ")[0]))
        end_labels_log(ax, ends)
        base = summary[(sc, METHOD_ORDER[0], 1)][3][0]
        ax.plot([1, 32], [base, base / 32], color=INK2, linewidth=1, linestyle=(0, (2, 2)),
                label="ideal linear (from W = 1)")
        ax.set_xscale("log", base=2); ax.set_yscale("log")
        ax.set_xticks([1, 2, 4, 8, 16, 32]); ax.set_xticklabels(["1", "2", "4", "8", "16", "32"])
        ax.set_title(sc); ax.set_xlabel("workers W (4 executors each)")
        ax.set_xlim(0.8, 70)
    axes[0].set_ylabel("RMST time to reach k* (s, virtual)")
    axes[0].legend(loc="lower left", fontsize=8)
    fig.suptitle("Fig. 1  Strong scaling: time to reach the true margin k*", x=0.01, ha="left", fontsize=10, fontweight="bold")
    fig.tight_layout(); fig.savefig(FIG / "fig1_strong_scaling.png", dpi=200); plt.close(fig)

    # Figure 2: speedup / efficiency (FRESCO) + weak scaling
    fig, axes = plt.subplots(1, 2, figsize=(8.4, 3.2))
    sp_ends = []
    for i, sc in enumerate(scen):
        Ws = [W for W in (1, 2, 4, 8, 16, 32) if (sc, METHOD_ORDER[0], W) in summary]
        base = summary[(sc, METHOD_ORDER[0], 1)][0]
        sp = [bootstrap_ratio_ci(base, summary[(sc, METHOD_ORDER[0], W)][0]) for W in Ws]
        axes[0].plot(Ws, [s[0] for s in sp], color=SERIES[i], label=sc, **MK)
        axes[0].fill_between(Ws, [s[1] for s in sp], [s[2] for s in sp], color=SERIES[i], alpha=0.1, linewidth=0)
        sp_ends.append((Ws[-1], sp[-1][0], f"{sp[-1][0]:.1f}x"))
    end_labels_log(axes[0], sp_ends)
    axes[0].plot([1, 32], [1, 32], color=INK2, linewidth=1, linestyle=(0, (2, 2)), label="ideal linear")
    axes[0].set_xscale("log", base=2); axes[0].set_yscale("log", base=2)
    axes[0].set_xticks([1, 2, 4, 8, 16, 32]); axes[0].set_xticklabels(["1", "2", "4", "8", "16", "32"])
    axes[0].set_xlim(0.8, 90)
    axes[0].set_title("Speedup of FRESCO (RMST(1) / RMST(W))"); axes[0].set_xlabel("workers W")
    axes[0].legend(fontsize=8, loc="upper left")
    weak = {W: g for (e, sc, m, W), g in groups.items() if e == "weak"}
    if weak:
        Ws = sorted(weak)
        base = times_calls(weak[1])[0]
        eff = [bootstrap_ratio_ci(base, times_calls(weak[W])[0]) for W in Ws]
        axes[1].plot(Ws, [e[0] for e in eff], color=SERIES[0], **MK)
        axes[1].fill_between(Ws, [e[1] for e in eff], [e[2] for e in eff], color=SERIES[0], alpha=0.1, linewidth=0)
        axes[1].axhline(1.0, color=INK2, linewidth=1, linestyle=(0, (2, 2)))
        axes[1].set_xscale("log", base=2); axes[1].set_xticks(Ws); axes[1].set_xticklabels([str(w) for w in Ws])
        axes[1].set_title("Weak scaling efficiency (violators ∝ 1/W)"); axes[1].set_xlabel("workers W")
        axes[1].set_ylabel("RMST(1) / RMST(W)")
        md.append("### Weak scaling (FRESCO; findable mass 0.16/W at level 3)\n")
        table(["W", "runs", "RMST time (s)", "efficiency RMST(1)/RMST(W)"],
              [[W, len(weak[W]), fmt_ci(bootstrap_ci(times_calls(weak[W])[0])), f"{e[0]:.2f} [{e[1]:.2f}, {e[2]:.2f}]"]
               for W, e in zip(Ws, eff)])
    fig.suptitle("Fig. 2  Speedup and weak-scaling efficiency", x=0.01, ha="left", fontsize=10, fontweight="bold")
    fig.tight_layout(); fig.savefig(FIG / "fig2_speedup_weak.png", dpi=200); plt.close(fig)

    # Figure 3: oracle calls to target vs W
    fig, axes = plt.subplots(1, len(scen), figsize=(4.2 * len(scen), 3.2), sharey=True)
    axes = np.atleast_1d(axes)
    for ax, sc in zip(axes, scen):
        for m in METHOD_ORDER:
            Ws = [W for W in (1, 2, 4, 8, 16, 32) if (sc, m, W) in summary or W == 1]
            vals = [(summary.get((sc, m, W)) or summary[(sc, METHOD_ORDER[0], 1)])[4] for W in Ws]
            ax.plot(Ws, [v[0] for v in vals], color=COLORS[m], label=m, **MK)
            ax.fill_between(Ws, [v[1] for v in vals], [v[2] for v in vals], color=COLORS[m], alpha=0.1, linewidth=0)
        ax.set_xscale("log", base=2); ax.set_xticks([1, 2, 4, 8, 16, 32]); ax.set_xticklabels(["1", "2", "4", "8", "16", "32"])
        ax.set_title(sc); ax.set_xlabel("workers W")
    axes[0].set_ylabel("mean oracle calls to reach k*\n(censored runs: all calls by H)")
    axes[0].legend(fontsize=8)
    fig.suptitle("Fig. 3  Oracle-call cost of reaching k*", x=0.01, ha="left", fontsize=10, fontweight="bold")
    fig.tight_layout(); fig.savefig(FIG / "fig3_oracle_calls.png", dpi=200); plt.close(fig)

    # Figure 4: Kaplan-Meier, W = 8, both scenarios
    fig, axes = plt.subplots(1, len(scen), figsize=(4.2 * len(scen), 3.2), sharey=True)
    axes = np.atleast_1d(axes)
    for ax, sc in zip(axes, scen):
        for m in METHOD_ORDER:
            if (sc, m, 8) not in summary:
                continue
            tv, te = summary[(sc, m, 8)][:2]
            t, s = kaplan_meier(tv, te)
            ax.step(t, s, where="post", color=COLORS[m], label=m)
        ax.set_xscale("log"); ax.set_title(f"{sc}, W = 8"); ax.set_xlabel("time (s, virtual)")
    axes[0].set_ylabel("P(k* not yet reached)")
    axes[0].legend(fontsize=8)
    fig.suptitle("Fig. 4  Time-to-target survival curves (Kaplan-Meier)", x=0.01, ha="left", fontsize=10, fontweight="bold")
    fig.tight_layout(); fig.savefig(FIG / "fig4_km_w8.png", dpi=200); plt.close(fig)

    # Figure 5 + table: communication overhead (FRESCO rows carry net stats)
    co = defaultdict(lambda: ([], []))
    for (e, sc, m, W), g in groups.items():
        if e == "strong" and m == METHOD_ORDER[0]:
            for r in g:
                if r.get("slots_leased"):
                    co[W][0].append(r["net"]["sent"] / r["slots_leased"])
                    co[W][1].append(r["ledger_ops"] / max(r["end_time"], 1.0))
    if co:
        Ws = sorted(co)
        md.append("### Communication overhead (FRESCO, both scenarios pooled)\n")
        table(["W", "messages per oracle call", "ledger ops per second (virtual)"],
              [[W, fmt_ci(bootstrap_ci(co[W][0]), 2), fmt_ci(bootstrap_ci(co[W][1]), 2)] for W in Ws])
        fig, axes = plt.subplots(1, 2, figsize=(8.4, 3.0))
        for ax, idx, title in ((axes[0], 0, "messages per oracle call"), (axes[1], 1, "ledger operations per second")):
            v = [np.mean(co[W][idx]) for W in Ws]
            ax.plot(Ws, v, color=SERIES[0], **MK)
            end_label(ax, Ws[-1], v[-1], f"{v[-1]:.1f}", SERIES[0])
            ax.set_xscale("log", base=2); ax.set_xticks(Ws); ax.set_xticklabels([str(w) for w in Ws])
            ax.set_title(title); ax.set_xlabel("workers W"); ax.set_xlim(0.8, 60)
        fig.suptitle("Fig. 5  Coordination cost of FRESCO", x=0.01, ha="left", fontsize=10, fontweight="bold")
        fig.tight_layout(); fig.savefig(FIG / "fig5_communication.png", dpi=200); plt.close(fig)


# ------------------------------------------------------------------ E1 / E4 validity
def validity():
    items = []
    if have("e1_validity"):
        g = defaultdict(list)
        for r in load("e1_validity"):
            g[(r["method"], r["W"])].append(int(r["false_confirmations"] > 0))
        for (m, W), v in sorted(g.items(), key=lambda x: (METHOD_ORDER.index(x[0][0]), x[0][1])):
            items.append((f"{m}, W={W}", sum(v), len(v)))
    if have("e4_alg1"):
        g = defaultdict(list)
        for r in load("e4_alg1"):
            if r["instance"] == "null-boundary":
                g[r["method"]] += [int(x[2]) for x in r["rows"]]
        names = {"alg1:wilson-T": "Algorithm 1 (manuscript: Wilson, eps/T)",
                 "alg1:cp-KT": "Algorithm 1 repaired (Clopper-Pearson, eps/KT)",
                 "lexis:matched": "LEXIS, matched budget", "lexis:open": "LEXIS, 30k budget"}
        for m in names:
            if m in g:
                items.append((names[m], sum(g[m]), len(g[m])))
    if not items:
        return
    md.append("## E1/E4 — validity on the boundary-null instance (every confirmation is false)\n")
    table(["method", "false / runs", "P(false confirmation) [95% Wilson]", f"<= eps = {EPS}?"],
          [[n, f"{k}/{t}", "{:.3f} [{:.3f}, {:.3f}]".format(*wilson(k, t)),
            "yes" if wilson(k, t)[1] <= EPS else "**NO**"] for n, k, t in items])
    fig, ax = plt.subplots(figsize=(7.2, 0.42 * len(items) + 1.0))
    for i, (n, k, t) in enumerate(items):
        p, lo, hi = wilson(k, t)
        bad = lo > EPS
        ax.plot([lo, hi], [i, i], color=SERIES[1] if bad else SERIES[0], linewidth=2)
        ax.plot([p], [i], color=SERIES[1] if bad else SERIES[0], **MK)
        ax.annotate(f"{p:.3f}", (hi, i), xytext=(5, 0), textcoords="offset points", va="center", fontsize=8, color=INK2)
    ax.axvline(EPS, color=INK, linewidth=1)
    ax.annotate("nominal ε = 0.05", (EPS, len(items) - 0.4), xytext=(4, 0), textcoords="offset points", fontsize=8, color=INK2)
    ax.set_yticks(range(len(items))); ax.set_yticklabels([n for n, _, _ in items], fontsize=8)
    ax.invert_yaxis(); ax.set_xlabel("P(any false confirmation), 95% Wilson interval")
    ax.set_xlim(0, max(0.35, max(wilson(k, t)[2] for _, k, t in items) + 0.05))
    from matplotlib.lines import Line2D
    ax.legend(handles=[Line2D([], [], color=SERIES[0], **MK, label="interval reaches ε or below"),
                       Line2D([], [], color=SERIES[1], **MK, label="interval entirely above ε (invalid)")],
              loc="lower right", fontsize=8)
    fig.suptitle("Fig. 6  Validity: false-confirmation probability at the boundary null",
                 x=0.01, ha="left", fontsize=10, fontweight="bold")
    fig.tight_layout(); fig.savefig(FIG / "fig6_validity.png", dpi=200); plt.close(fig)


def e4_efficiency():
    if not have("e4_alg1"):
        return
    g = defaultdict(list)
    rows_all = load("e4_alg1") + (load("e4b_lexis_cap30_exploratory") if have("e4b_lexis_cap30_exploratory") else [])
    for r in rows_all:
        if r["instance"] != "null-boundary":
            label = r["method"] + (" (exploratory, post hoc)" if r["method"].endswith(":cap30") else "")
            g[(r["instance"], label)] += r["rows"]
    md.append("## E4 — efficiency: LEXIS vs Algorithm 1 (slot level, single process)\n")
    md.append("k* = 3 in both instances. 'Reach k*' means b_hat = 3 exactly. Algorithm 1 is a single pass "
              "(at most 1,160 slots); 'LEXIS, matched' has the same 1,160-slot budget.\n")
    if have("e4b_lexis_cap30_exploratory"):
        nb = [x for r in load("e4b_lexis_cap30_exploratory") if r["instance"] == "null-boundary" for x in r["rows"]]
        k = sum(int(x[2]) for x in nb)
        md.append("Exploratory cap-30 LEXIS on the boundary null: false confirmations "
                  "{}/{} = {:.3f} [{:.3f}, {:.3f}].\n".format(k, len(nb), *wilson(k, len(nb))))
    rows = []
    for (inst, m), v in sorted(g.items()):
        reach = [b == 3 for b, _, _ in v]
        slots_reach = [s for b, s, _ in v if b == 3]
        p = wilson(sum(reach), len(reach))
        rows.append([inst, m, len(v), "{:.3f} [{:.3f}, {:.3f}]".format(*p),
                     f"{np.median(slots_reach):,.0f}" if slots_reach else "—",
                     f"{np.mean([b is not None and b > 3 for b, _, _ in v]):.3f}"])
    table(["instance", "method", "runs", "P(reach k*)", "median slots (reached runs)", "P(b_hat > k*)"], rows)


def e5():
    if not have("e5_ablations"):
        return
    g = defaultdict(list)
    for r in load("e5_ablations"):
        g[r["variant"]].append(r)
    names = list(g)
    base_name = names[0]
    btv = times_calls(g[base_name])[0]
    rows, plot = [], []
    for n in names:
        tv, te, calls = times_calls(g[n])
        ratio = bootstrap_ratio_ci(tv, btv)
        rows.append([n, len(tv), "{:.2f} [{:.2f}, {:.2f}]".format(*wilson(int(te.sum()), len(te))),
                     fmt_ci(bootstrap_ci(tv)), fmt_ci(bootstrap_ci(calls)), f"{ratio[0]:.2f} [{ratio[1]:.2f}, {ratio[2]:.2f}]",
                     sum(r["false_confirmations"] for r in g[n])])
        plot.append((n, ratio))
    md.append("## E5 — ablations and sensitivity (W = 8 unless stated, S1-moderate)\n")
    table(["variant", "runs", "P(reach k*)", "RMST time (s)", "mean calls", "RMST ratio vs default", "false conf."], rows)
    fig, ax = plt.subplots(figsize=(7.4, 0.36 * len(plot) + 1.0))
    for i, (n, (v, lo, hi)) in enumerate(plot):
        c = SERIES[0] if i == 0 else (SERIES[1] if lo > 1 else (SERIES[2] if hi < 1 else INK2))
        ax.plot([lo, hi], [i, i], color=c, linewidth=2)
        ax.plot([v], [i], color=c, **MK)
    ax.axvline(1.0, color=INK, linewidth=1)
    ax.set_xscale("log"); ax.set_yticks(range(len(plot))); ax.set_yticklabels([p[0] for p in plot], fontsize=7.5)
    ticks = [0.25, 0.5, 1, 2, 4]
    ax.xaxis.set_major_locator(matplotlib.ticker.FixedLocator(ticks))
    ax.xaxis.set_minor_locator(matplotlib.ticker.NullLocator())
    ax.set_xticklabels([f"{t:g}×" for t in ticks])
    ax.invert_yaxis(); ax.set_xlabel("RMST time ratio vs default (log scale; < 1 = faster)")
    from matplotlib.lines import Line2D
    ax.legend(handles=[Line2D([], [], color=SERIES[2], **MK, label="faster (CI below 1)"),
                       Line2D([], [], color=SERIES[1], **MK, label="slower (CI above 1)"),
                       Line2D([], [], color=INK2, **MK, label="no detected difference")],
              loc="lower right", fontsize=7.5)
    fig.suptitle("Fig. 8  Ablations: effect on time to reach k* (W = 8, S1)", x=0.01, ha="left",
                 fontsize=10, fontweight="bold")
    fig.tight_layout(); fig.savefig(FIG / "fig8_ablations.png", dpi=200); plt.close(fig)


def e6():
    if not have("e6_recovery"):
        return
    g = defaultdict(list)
    for r in load("e6_recovery"):
        g[r["variant"]].append(r["series"])
    fig, ax = plt.subplots(figsize=(7.4, 3.2))
    rows = []
    ends = {"ledger crash (60 s down)": 1060, "4 of 8 workers crash (120 s down)": 1120,
            "4 of 8 workers partitioned (300 s)": 1300, "no fault": 1000}
    for i, (n, ss) in enumerate(g.items()):
        L = min(len(s) for s in ss)
        mean = np.mean([s[:L] for s in ss], axis=0) / 20.0
        t = np.arange(L) * 20.0 + 10
        ax.plot(t, mean, color=SERIES[i], label=n, linewidth=1.6)
        pre = mean[(t > 500) & (t < 1000)].mean()
        after = np.nonzero((t >= ends[n]) & (mean >= 0.9 * pre))[0]
        rec = (t[after[0]] - ends[n]) if len(after) else math.nan
        lost = float(np.sum(np.maximum(0, pre - mean[(t >= 1000) & (t < 2000)])) * 20.0)
        rows.append([n, len(ss), f"{pre:.2f}", f"{rec:.0f}" if n != "no fault" else "—", f"{lost:,.0f}"])
    ax.axvline(1000, color=INK2, linewidth=1, linestyle=(0, (2, 2)))
    ax.annotate("fault injected", (1000, ax.get_ylim()[1] * 0.97), xytext=(4, 0), textcoords="offset points",
                fontsize=8, color=INK2, va="top")
    ax.set_xlabel("time (s, virtual)"); ax.set_ylabel("oracle calls per second (mean over seeds)")
    ax.legend(fontsize=7.5, loc="lower right")
    ax.set_title("Fig. 9  Fault-recovery timeline (W = 8)", loc="left")
    fig.tight_layout(); fig.savefig(FIG / "fig9_recovery.png", dpi=200); plt.close(fig)
    md.append("## E6 — fault recovery (W = 8, 20 s buckets)\n")
    table(["variant", "seeds", "pre-fault calls/s", "recovery to 90% after fault end (s)", "calls lost in [1000, 2000) s"], rows)


def e7():
    if not have("e7_certificates"):
        return
    g = defaultdict(list)
    for r in load("e7_certificates"):
        g[r["variant"]].append(r)
    md.append("## E7 — certificate calibration (G2)\n")
    md.append("Levels 1-2 contain rare violators (mu = 0.003, 0.01; p = 0.3 > alpha), levels 3-4 none. "
              "Coverage requires eta_k >= mu_k at every level simultaneously; target >= 1 - eps_audit = 0.95.\n")
    rows = []
    for n, rs in g.items():
        cover = [all(r["certificates"][str(k)]["eta"] >= r["mu"][k - 1] - 1e-12 for k in range(1, 5)) for r in rs]
        p = wilson(sum(cover), len(cover))
        etas = [[r["certificates"][str(k)]["eta"] for r in rs] for k in range(1, 5)]
        ns = [[r["certificates"][str(k)]["n"] for r in rs] for k in range(1, 5)]
        rows.append([n, len(rs), "{:.3f} [{:.3f}, {:.3f}]".format(*p)] +
                    [f"{np.median(e):.3f} (N≈{np.median(m):.0f})" for e, m in zip(etas, ns)])
    table(["variant", "runs", "coverage", "median eta_1 (mu=.003)", "eta_2 (mu=.01)", "eta_3 (mu=0)", "eta_4 (mu=0)"], rows)


def main():
    FIG.mkdir(exist_ok=True)
    OUT.mkdir(parents=True, exist_ok=True)
    md.append("# Stage 4 results (synthetic oracles; generated by analysis/make_figures.py)\n")
    if have("e2_scaling"):
        e2()
    validity()
    e4_efficiency()
    e5()
    e6()
    e7()
    (OUT / "summary.md").write_text("\n".join(md))
    print(f"wrote {OUT / 'summary.md'} and figures in {FIG}")


if __name__ == "__main__":
    main()
