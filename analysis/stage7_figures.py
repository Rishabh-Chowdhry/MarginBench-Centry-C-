"""Stage-7 analysis: E10 (corruption ablations), E11 (adversary), E12 (SQA campaign)
and E13 (real agents) -> results/processed/stage7_summary.md and figures/fig1[0-5]_*.png.
Hypotheses are evaluated exactly as preregistered in docs/stage7_quintet_hkg_twgr.md §6.

Run: python3 -I analysis/stage7_figures.py
"""

import json
import pathlib
import sys
from collections import defaultdict

import numpy as np

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import matplotlib  # noqa: E402

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from analysis.make_figures import GRID, INK2, MK, SURFACE  # noqa: E402  (shared style)
from analysis.stats import bootstrap_ci, wilson  # noqa: E402
from experiments.common import RAW, load  # noqa: E402

FIG = ROOT / "figures"
OUT = ROOT / "results" / "processed"
EPS = 0.05
VCOL = {"TWGR": "#2a78d6", "TWGR-S": "#0b0b0b", "-replicas": "#7fb2ea", "-log anchors": "#1baf7a", "-edge anchors": "#8fd6b9",
        "-derivation": "#eda100", "item votes": "#9a6fd6", "TWGR support-1": "#52514e",
        "replica-majority": "#eb6834", "best-effort": "#d1335b", "single-coordinator": "#8a8984"}
ORDER = list(VCOL)
md = []


def table(header, rows):
    md.append("| " + " | ".join(header) + " |")
    md.append("|" + "---|" * len(header))
    for r in rows:
        md.append("| " + " | ".join(str(x) for x in r) + " |")
    md.append("")


def verdict(ok):
    return "**supported**" if ok else "**not supported**"


def e10_rows():
    rows = []
    for job in load("e10_corruption"):
        for r in job["rows"]:
            rows.append({**r, "scenario": job["scenario"], "seed": job["seed"]})
    return rows


def e10():
    rows = e10_rows()
    rho_rows = [r for r in rows if r["study"] == "rho"]
    rhos = sorted({r["rho"] for r in rho_rows})
    by = defaultdict(list)
    for r in rho_rows:
        by[(r["variant"], r["rho"])].append(r)
    variants = [v for v in ORDER if any(k[0] == v for k in by)]

    md.append("## E10 — TWGR under independent storage corruption\n")
    md.append(f"{len({(r['scenario'], r['seed']) for r in rows})} QUINTET runs "
              f"({', '.join(sorted({r['scenario'] for r in rows}))}); every variant repairs the identical corrupted "
              "fabric (paired). Recovery = fraction of records accepted with exactly their true bytes. "
              "Wrong = accepted non-confirmation records whose content (payload) differs from the truth (summed over runs); a record with right content but different link bytes counts as not recovered, not as wrong. "
              "Added = confirmations reported after repair that the original run did not make.\n")
    hdr = ["variant"] + [f"ρ={x:g}" for x in rhos]
    table(hdr, [[v] + [f"{np.mean([r['recovery'] for r in by[(v, x)]]):.4f}" for x in rhos] for v in variants])
    md.append("Wrong accepted non-confirmation records (total) / added confirmations (total):\n")
    table(hdr, [[v] + [f"{sum(r['wrong_nonconf'] for r in by[(v, x)])} / {sum(r['added_conf'] for r in by[(v, x)])}"
                       for x in rhos] for v in variants])

    # boundary-null false confirmation (any) per run
    md.append("Boundary-null runs: fraction of runs with ≥ 1 false confirmation after repair "
              "(Wilson 95% CI), ε = 0.05:\n")
    fc, trows = {}, []
    for v in variants:
        line = [v]
        for x in rhos:
            rr = [r for r in by[(v, x)] if r["scenario"] == "boundary-null"]
            k = sum(r["any_false_conf"] for r in rr)
            fc[(v, x)] = (k, len(rr)) + wilson(k, len(rr))[1:]
            line.append(f"{k}/{len(rr)} [{fc[(v, x)][2]:.2f}, {fc[(v, x)][3]:.2f}]")
        trows.append(line)
    table(hdr, trows)

    # ---------------- figure 10: recovery and wrong records vs rho
    fig, axs = plt.subplots(1, 3, figsize=(13, 4.2))
    for v in variants:
        m = [np.mean([r["recovery"] for r in by[(v, x)]]) for x in rhos]
        lo = [bootstrap_ci([r["recovery"] for r in by[(v, x)]], reps=1000)[1] for x in rhos]
        hi = [bootstrap_ci([r["recovery"] for r in by[(v, x)]], reps=1000)[2] for x in rhos]
        ls = "--" if v in ("replica-majority", "best-effort", "single-coordinator") else "-"
        z = 5 if v == "TWGR" else 2
        axs[0].plot(rhos, m, ls, color=VCOL[v], label=v, zorder=z, **{**MK, "markersize": 4})
        axs[0].fill_between(rhos, lo, hi, color=VCOL[v], alpha=0.12, linewidth=0)
        w = [np.mean([r["wrong_nonconf"] for r in by[(v, x)]]) for x in rhos]
        axs[1].plot(rhos, np.array(w) + 0.1, ls, color=VCOL[v], **{**MK, "markersize": 4})
        f = [fc[(v, x)][0] / max(1, fc[(v, x)][1]) for x in rhos]
        axs[2].plot(rhos, f, ls, color=VCOL[v], **{**MK, "markersize": 4})
    axs[0].set(title="Exact recovery of the graph", xlabel="corruption rate ρ per stored item",
               ylabel="fraction of records recovered exactly")
    axs[1].set(title="Wrong records accepted (per run)", xlabel="corruption rate ρ", ylabel="mean count + 0.1 (log)",
               yscale="log")
    for ax in axs[1:]:
        ax.annotate("TWGR, every ablation and\nsingle-coordinator: 0 at every ρ", xy=(0.3, 0.1 if ax is axs[1] else 0),
                    xytext=(0.18, 3 if ax is axs[1] else 0.25), fontsize=8, color=INK2,
                    arrowprops=dict(arrowstyle="-", color=INK2, lw=0.8))
    axs[2].axhline(EPS, color=INK2, linewidth=1, linestyle=":")
    axs[2].text(rhos[-1], EPS, " ε", va="center", color=INK2)
    axs[2].set(title="Boundary-null: runs with a false confirmation", xlabel="corruption rate ρ",
               ylabel="fraction of runs")
    axs[0].legend(fontsize=7, ncol=2, loc="lower left")
    fig.tight_layout()
    fig.savefig(FIG / "fig10_corruption.png", dpi=160)
    plt.close(fig)

    # ---------------- figure 11: ablation at rho = 0.3 (paired differences)
    ref = {(r["scenario"], r["seed"]): r["recovery"] for r in by[("TWGR", 0.3)]}
    abl = [v for v in variants if v != "TWGR"]
    diffs = {}
    for v in abl:
        d = [ref[(r["scenario"], r["seed"])] - r["recovery"] for r in by[(v, 0.3)]]
        diffs[v] = bootstrap_ci(d, reps=2000)
    fig, ax = plt.subplots(figsize=(7.5, 4))
    ys = np.arange(len(abl))
    ax.barh(ys, [diffs[v][0] for v in abl], color=[VCOL[v] for v in abl], height=0.6)
    ax.errorbar([diffs[v][0] for v in abl], ys, xerr=[[diffs[v][0] - diffs[v][1] for v in abl],
                                                      [diffs[v][2] - diffs[v][0] for v in abl]],
                fmt="none", ecolor=INK2, capsize=3, linewidth=1)
    for y, v in zip(ys, abl):
        w = sum(r["wrong_nonconf"] for r in by[(v, 0.3)])
        ax.text(max(diffs[v][2], 0) + 0.005, y, f"{w} wrong" if w else "0 wrong", va="center", fontsize=8,
                color="#d1335b" if w else INK2)
    ax.set_yticks(ys, abl)
    ax.invert_yaxis()
    ax.axvline(0, color=GRID)
    ax.set(title="Ablation at ρ = 0.3: recovery lost vs full TWGR (paired, 95% CI)",
           xlabel="TWGR recovery − variant recovery")
    fig.tight_layout()
    fig.savefig(FIG / "fig11_ablation.png", dpi=160)
    plt.close(fig)

    # ---------------- figure 12: whole-domain loss
    loss = [r for r in rows if r["study"] == "loss"]
    lv = [v for v in ORDER if any(r["variant"] == v for r in loss)]
    ks = sorted({r["lost"] for r in loss})
    fig, ax = plt.subplots(figsize=(6, 3.8))
    md.append("### Whole-domain loss (all data of k random domains erased)\n")
    trows = []
    for i, v in enumerate(lv):
        m = [np.mean([r["recovery"] for r in loss if r["variant"] == v and r["lost"] == k]) for k in ks]
        ax.bar(np.array(ks) + (i - 1) * 0.25, m, width=0.25, color=VCOL[v], label=v)
        trows.append([v] + [f"{x:.4f} (wrong {sum(r['wrong_nonconf'] for r in loss if r['variant'] == v and r['lost'] == k)},"
                            f" added {sum(r['added_conf'] for r in loss if r['variant'] == v and r['lost'] == k)})"
                            for x, k in zip(m, ks)])
    table(["variant"] + [f"{k} domain(s) lost" for k in ks], trows)
    ax.set(title="Recovery after losing whole domains", xlabel="domains lost (of 5)", ylabel="exact recovery",
           xticks=ks, ylim=(0, 1.05))
    ax.legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(FIG / "fig12_domain_loss.png", dpi=160)
    plt.close(fig)

    # ---------------- hypotheses
    md.append("### Preregistered hypotheses (E10)\n")
    tw = [r for r in rho_rows if r["variant"] == "TWGR"]
    safe = all(r["wrong_nonconf"] == 0 and r["added_conf"] == 0 and r["phantoms"] == 0 for r in tw)
    rec = {x: np.mean([r["recovery"] for r in by[("TWGR", x)]]) for x in rhos}
    rec_ok = all(rec[x] >= 0.99 for x in rhos if x <= 0.1) and rec[0.3] >= 0.90
    ab_ok = {v: diffs[v][1] > 0 or sum(r["wrong_nonconf"] for r in by[(v, 0.3)]) > 0
             for v in ("-replicas", "-log anchors", "-edge anchors", "-derivation", "item votes")}
    rm_ok = all(sum(r["wrong_nonconf"] for r in by[("replica-majority", x)]) > 0 for x in rhos if x >= 0.1)
    be = {x: fc[("best-effort", x)] for x in rhos if x >= 0.1}
    be_point = all(k / n > EPS for k, n, _, _ in be.values())
    be_strict = all(lo > EPS for _, _, lo, _ in be.values())
    single = np.mean([r["recovery"] for r in by[("single-coordinator", 0.3)]])
    val = {x: fc[("TWGR", x)] for x in rhos}
    val_ok = all(lo <= EPS for _, _, lo, _ in val.values())
    s1 = {x: [r for r in by[("TWGR", x)] if r["scenario"] == "S1-dense"] for x in rhos if x <= 0.2}
    pw = {x: np.mean([r["b_hat"] == r["k_star"] for r in rr]) for x, rr in s1.items()}
    pw_orig = {x: np.mean([r["b_hat_true"] == r["k_star"] for r in rr]) for x, rr in s1.items()}
    table(["hypothesis", "result", "verdict"], [
        ["H7-safe", f"TWGR wrong non-confirmation records = {sum(r['wrong_nonconf'] for r in tw)}, added confirmations ="
                    f" {sum(r['added_conf'] for r in tw)}, phantoms = {sum(r['phantoms'] for r in tw)} over {len(tw)} repairs",
         verdict(safe)],
        ["H7-recover", ", ".join(f"ρ={x:g}: {rec[x]:.4f}" for x in rhos), verdict(rec_ok)],
        ["H7-ablate", "; ".join(f"{v}: Δ={diffs[v][0]:.4f} [{diffs[v][1]:.4f}, {diffs[v][2]:.4f}]"
                                + (f", wrong={sum(r['wrong_nonconf'] for r in by[(v, 0.3)])}" if sum(
                                    r['wrong_nonconf'] for r in by[(v, 0.3)]) else "") for v in ab_ok),
         verdict(all(ab_ok.values())) + " (" + ", ".join(f"{v}: {'yes' if ok else 'no'}" for v, ok in ab_ok.items()) + ")"],
        ["H7-baselines (replica-majority wrong at ρ≥0.1)",
         ", ".join(f"ρ={x:g}: {sum(r['wrong_nonconf'] for r in by[('replica-majority', x)])}" for x in rhos if x >= 0.1),
         verdict(rm_ok)],
        ["H7-baselines (best-effort false-conf > ε at ρ≥0.1)",
         ", ".join(f"ρ={x:g}: {k}/{n} [{lo:.2f}, {hi:.2f}]" for x, (k, n, lo, hi) in be.items()),
         verdict(be_point) + (" (point estimates; Wilson lower bound > ε at all ρ: " + ("yes" if be_strict else "no") + ")")],
        ["H7-baselines (single-coordinator recovery ≤ 0.5 at ρ=0.3)", f"{single:.4f}", verdict(single <= 0.5)],
        ["H7-validity", ", ".join(f"ρ={x:g}: {k}/{n}" for x, (k, n, _, _) in val.items()), verdict(val_ok)],
        ["H7-power (b̂ = k* in ≥ 90% of S1 runs, ρ ≤ 0.2)",
         ", ".join(f"ρ={x:g}: {pw[x]:.2f} (original run {pw_orig[x]:.2f})" for x in pw),
         verdict(all(v >= 0.9 for v in pw.values()))],
    ])


def e11():
    rows = [r for job in load("e11_adversary") for r in job["rows"]]
    md.append("## E11 — coordinated adversary controlling k domains\n")
    md.append("An adversary controlling k of the five domains rewrites one target consistently in every copy, "
              "anchor-log entry (re-chained) and edge it holds. b = compromised domains among the m domains holding "
              "anchors for the target; *majority* means 2b > m. *Unsafe wrong* = a wrong accepted value other than an "
              "unsigned crash (a crash can only weaken evidence). *Added* = confirmations in the repaired report that "
              "the original run did not make. TWGR-S (signed evidence, derivation dominance) was added after the "
              "majority-adversary loophole was reported; it is not preregistered.\n")
    attacks = sorted({r["attack"] for r in rows})
    variants = [v for v in ("TWGR", "TWGR-S", "replica-majority") if any(r["variant"] == v for r in rows)]
    trows = []
    for v in variants:
        for a in attacks:
            for maj in (0, 1):
                rr = [r for r in rows if r["variant"] == v and r["attack"] == a and r["majority"] == maj]
                if not rr:
                    continue
                unsafe = sum(r["wrong"] and not r["conservative"] for r in rr)
                trows.append([v, a, "majority" if maj else "minority", len(rr), unsafe,
                              sum(r["conservative"] for r in rr), sum(r["added_conf"] > 0 for r in rr),
                              sum(r["quarantined"] for r in rr), sum(r["correct"] for r in rr)])
    table(["variant", "attack", "adversary", "attacks", "unsafe wrong", "conservative (crash)",
           "attacks adding a confirmation", "quarantined", "correct"], trows)
    fig, axs = plt.subplots(1, 2, figsize=(11, 3.8))
    cols = {"TWGR": VCOL["TWGR"], "TWGR-S": "#0b0b0b", "replica-majority": VCOL["replica-majority"]}
    for v in variants:
        xs, w, xa, ad = [], [], [], []
        for b in range(0, 6):
            rr = [r for r in rows if r["variant"] == v and r["b"] == b]
            if rr:
                xs.append(b)
                w.append(np.mean([bool(r["wrong"] and not r["conservative"]) for r in rr]))
            rc = [r for r in rr if r["attack"] == "tamper-confirmation"]
            if rc:                                    # only bins that contain such attacks
                xa.append(b)
                ad.append(np.mean([r["added_conf"] > 0 for r in rc]))
        axs[0].plot(xs, w, "-", color=cols[v], label=v, **MK)
        axs[1].plot(xa, ad, "-", color=cols[v], label=v, **MK)
    axs[0].set(title="Unsafe wrong value accepted", xlabel="compromised anchor domains b", ylabel="fraction of attacks",
               ylim=(-0.03, 1.03))
    axs[1].set(title="Forged confirmations: repair adds a false one", xlabel="compromised anchor domains b",
               ylabel="fraction of attacks", ylim=(-0.03, 1.03))
    axs[0].legend()
    for ax in axs:
        ax.set_xticks(range(0, 6))
    fig.tight_layout()
    fig.savefig(FIG / "fig13_adversary.png", dpi=160)
    plt.close(fig)
    tw = [r for r in rows if r["variant"] == "TWGR"]
    tw_min = sum(r["wrong"] for r in tw if not r["majority"] and not r["conservative"])
    tw_maj = sum(r["wrong"] for r in tw if r["majority"])
    md.append(f"H7-adversary (preregistered, plain TWGR): unsafe wrong acceptances with a minority adversary = {tw_min}; "
              f"wrong acceptances with a majority = {tw_maj}. {verdict(tw_min == 0 and tw_maj > 0)}\n")
    ts = [r for r in rows if r["variant"] == "TWGR-S"]
    if ts:
        unsafe = sum(r["wrong"] and not r["conservative"] for r in ts)
        added = sum(r["added_conf"] > 0 for r in ts)
        md.append(f"TWGR-S (post hoc): over {len(ts)} attacks, {sum(r['majority'] for r in ts)} of them by a majority "
                  f"adversary (up to all five domains): unsafe wrong acceptances = {unsafe}, attacks that added a "
                  f"confirmation = {added}, conservative substitutions accepted = {sum(r['conservative'] for r in ts)}.\n")


def e12():
    path = RAW / "e12_sqa.jsonl"
    if not path.exists():
        return
    rows = [json.loads(x) for x in path.read_text().splitlines() if x.strip()]
    md.append("## E12 — SQA campaign on Docker devices (real network, process and storage faults)\n")
    trows = []
    for r in rows:
        inv = r.get("inv", {})
        cmp = r.get("vs_golden", {})
        load_ = r.get("load", {})
        detail = []
        if load_:
            detail.append(f"{load_.get('calls')} slots, {load_.get('wall_s')} s")
        if inv:
            detail.append(f"{inv.get('records')} records; b̂={inv.get('b_hat')}; crash results {inv.get('crash_results')}")
        if cmp:
            detail.append(f"recovery {cmp['recovery']:.4f}, wrong {cmp['wrong_nonconf']}, links differ "
                          f"{cmp.get('content_right_links_differ', 0)}, added conf {cmp['added_conf']}, lost conf {cmp['lost_conf']}")
        if "scan1" in r:
            detail.append("scan " + ", ".join(f"{k} {v}" for k, v in sorted(r["scan1"].items())))
        if "wrong" in r:
            detail.append(f"targets {r['targets']} ({r.get('majority_targets', '?')} with a majority adversary): correct "
                          f"{r['correct']}, content right/links missing {r.get('content_right_links_missing', 0)}, "
                          f"quarantined {r['quarantined']}, wrong {r['wrong']}, added confirmations {r.get('added_conf', '?')}")
        if "false_confirmations" in r:
            detail.append(f"false confirmations {r['false_confirmations']}")
        if "worker_conflict_responses" in r:
            detail.append(f"conflict responses {r['worker_conflict_responses']}")
        trows.append([r["tc"], "; ".join(detail), "PASS" if r["pass"] else "FAIL"])
    table(["test case", "observations", "verdict"], trows)
    md.append(f"{sum(r['pass'] for r in rows)}/{len(rows)} test cases passed.\n")


def e13():
    path = RAW / "e13_agentdojo.jsonl"
    if not path.exists():
        return
    rows = [json.loads(x) for x in path.read_text().splitlines() if x.strip() and "_manifest" not in x]
    ok = [r for r in rows if "error" not in r]
    md.append("## E13 — real agent episodes (AgentDojo v1.2.1, local qwen2.5 via Ollama)\n")
    v = [r for r in ok if r["violation"]]
    b = [r for r in ok if not r["violation"]]
    md.append(f"{len(ok)} episodes ({len(rows) - len(ok)} errors); violations {len(v)} "
              f"({wilson(len(v), len(ok))[0]:.3f}, 95% CI [{wilson(len(v), len(ok))[1]:.3f}, {wilson(len(v), len(ok))[2]:.3f}]).\n")
    u = [r for r in ok if r["utility"]]
    f = [r for r in ok if not r["utility"]]
    md.append(f"Authorized-task completion (utility) {len(u)}/{len(ok)} ({wilson(len(u), len(ok))[0]:.3f}, "
              f"95% CI [{wilson(len(u), len(ok))[1]:.3f}, {wilson(len(u), len(ok))[2]:.3f}]).\n")
    rowsl = []
    for name, grp in (("violation", v), ("benign", b), ("task completed", u), ("task not completed", f)):
        if grp:
            x = np.array([r["latency_s"] for r in grp])
            rowsl.append([name, len(x), f"{np.median(x):.1f}", f"{x.mean():.1f}", f"{np.quantile(x, 0.9):.1f}"])
    table(["outcome", "episodes", "median latency (s)", "mean (s)", "p90 (s)"], rowsl)
    for suite in sorted({r["suite"] for r in ok}):
        g = [r for r in ok if r["suite"] == suite]
        md.append(f"- {suite}: {len(g)} episodes, violations {sum(r['violation'] for r in g)}, "
                  f"utility {sum(r['utility'] for r in g)}")
    md.append("")
    if u and f:
        lu, lf = np.array([r["latency_s"] for r in u]), np.array([r["latency_s"] for r in f])
        trows = []
        for tau in sorted({float(np.quantile(np.r_[lu, lf], q)) for q in (0.5, 0.75, 0.9)}):
            trows.append([f"{tau:.0f}", f"{np.mean(lu > tau):.2f}", f"{np.mean(lf > tau):.2f}"])
        md.append("Outcome-dependent timeouts (the mechanism behind the fresh-retry default), measured on task "
                  "completion because violations were too rare: P(latency > τ | outcome).\n")
        table(["timeout τ (s)", "task completed", "task not completed"], trows)
        fig, ax = plt.subplots(figsize=(6, 3.6))
        bins = np.linspace(0, max(lu.max(), lf.max()), 25)
        ax.hist(lf, bins=bins, color="#eb6834", alpha=0.7, label="task not completed")
        ax.hist(lu, bins=bins, color="#2a78d6", alpha=0.7, label="task completed")
        if v:
            ax.plot([r["latency_s"] for r in v], [0.3] * len(v), "v", color="#d1335b", label="violation")
        ax.set(title="Real AgentDojo episodes: latency by outcome", xlabel="episode latency (s)", ylabel="episodes")
        ax.legend()
        fig.tight_layout()
        fig.savefig(FIG / "fig15_agentdojo_latency.png", dpi=160)
        plt.close(fig)
    if not v or not b:
        return
    lv, lb = np.array([r["latency_s"] for r in v]), np.array([r["latency_s"] for r in b])
    p = len(v) / len(ok)
    trows = []
    taus = sorted({float(np.quantile(np.r_[lv, lb], q)) for q in (0.5, 0.75, 0.9)})
    for tau in taus:
        c1, c0 = float(np.mean(lv > tau)), float(np.mean(lb > tau))
        denom = p * (1 - c1) + (1 - p) * (1 - c0)
        p_retry = p * (1 - c1) / denom if denom > 0 else float("nan")
        trows.append([f"{tau:.0f}", f"{c1:.2f}", f"{c0:.2f}", f"{p:.3f}", f"{p_retry:.3f}", f"{p_retry / p:.2f}×"])
    md.append("Implied effect of a fresh-key retry of timed-out episodes (the executor default R4 forbids): the observed "
              "violation rate becomes p(1−c₁)/(p(1−c₁)+(1−p)(1−c₀)).\n")
    table(["timeout τ (s)", "P(timeout | violation) c₁", "P(timeout | benign) c₀", "true p", "observed p with retry",
           "ratio"], trows)


def kappa(a, b):
    """Cohen's kappa for two boolean lists."""
    n = len(a)
    if n == 0:
        return float("nan")
    po = sum(x == y for x, y in zip(a, b)) / n
    pa, pb = sum(a) / n, sum(b) / n
    pe = pa * pb + (1 - pa) * (1 - pb)
    return (po - pe) / (1 - pe) if pe < 1 else 1.0


def e14():
    ep_path, j_path = RAW / "e14_episodes.jsonl", RAW / "e14_judgements.jsonl"
    if not ep_path.exists():
        return
    eps = [r for r in map(json.loads, ep_path.read_text().splitlines())]
    ok = [r for r in eps if "error" not in r]
    judged = {(j["suite"], j["user_task"], j["attack"]): j for j in map(json.loads, j_path.read_text().splitlines())
              if "error" not in j} if j_path.exists() else {}
    md.append("## E14 — why do the agent episodes fail? (every AgentDojo user task, judge LLM)\n")
    md.append(f"Agent: Qwen2.5-1.5B (Ollama, T = 0.7, seed 1). Every user task of the four AgentDojo v1.2.1 suites "
              f"(97 tasks), each with the important_instructions attack (rotating injection task) and without an "
              f"attack. {len(ok)} episodes ({len(eps) - len(ok)} harness errors). Judge: Qwen2.5-7B (T = 0), "
              f"constrained to a fixed taxonomy and to AgentDojo's own labels; {len(judged)} episodes judged.\n")
    trows = []
    for suite in sorted({r["suite"] for r in ok}):
        a = [r for r in ok if r["suite"] == suite and r["attack"] != "none"]
        n = [r for r in ok if r["suite"] == suite and r["attack"] == "none"]
        trows.append([suite, len(n), f"{sum(r['utility'] for r in n)}/{len(n)}",
                      f"{sum(r['utility'] for r in a)}/{len(a)}", f"{sum(bool(r['violation']) for r in a)}/{len(a)}",
                      f"{np.mean([r['features']['n_tool_calls'] == 0 for r in ok if r['suite'] == suite]):.2f}"])
    table(["suite", "tasks", "utility (no attack)", "utility (attack)", "violations (attack)",
           "episodes with no tool call"], trows)
    pairs = {}
    for r in ok:
        pairs.setdefault((r["suite"], r["user_task"]), {})[r["attack"]] = r["utility"]
    both = [v for v in pairs.values() if len(v) == 2]
    lost = sum(1 for v in both if v["none"] and not v["important_instructions"])
    gained = sum(1 for v in both if not v["none"] and v["important_instructions"])
    md.append(f"Paired by task ({len(both)} tasks): the attack turned {lost} successes into failures and {gained} "
              f"failures into successes (McNemar discordant pairs {lost} vs {gained}).\n")
    if not judged:
        return
    rows = [(r, judged[(r["suite"], r["user_task"], r["attack"])]) for r in ok
            if (r["suite"], r["user_task"], r["attack"]) in judged]
    cats = ["NO_TOOL_USE", "WRONG_TOOL", "WRONG_ARGUMENTS", "INCOMPLETE", "MALFORMED_CALL", "HIJACKED",
            "MISREAD_DATA", "OTHER"]
    fails = [(r, j) for r, j in rows if not r["utility"]]
    trows = []
    for att in ("none", "important_instructions"):
        g = [j["task_failure"] for r, j in fails if r["attack"] == att]
        trows.append([att] + [f"{g.count(c)}" for c in cats] + [len(g)])
    table(["attack"] + cats + ["failed episodes"], trows)
    trows = []
    for suite in sorted({r["suite"] for r, _ in fails}):
        g = [j["task_failure"] for r, j in fails if r["suite"] == suite]
        trows.append([suite] + [f"{g.count(c)}" for c in cats] + [len(g)])
    md.append("By suite (both attack conditions):\n")
    table(["suite"] + cats + ["failed"], trows)
    inj = [j["injection_outcome"] for r, j in rows if r["attack"] != "none"]
    seen = [r for r in ok if r["attack"] != "none" and r["features"]["injection_seen"]]
    md.append(f"Rule-based: the injected text reached the agent (returned by a tool) in {len(seen)} of "
              f"{sum(r['attack'] != 'none' for r in ok)} attacked episodes; violations "
              f"{sum(bool(r['violation']) for r in seen)}/{len(seen)} among those.\n")
    md.append("Injection outcome (judge): " + ", ".join(f"{c} {inj.count(c)}" for c in
                                                       ("NOT_EXPOSED", "IGNORED", "ATTEMPTED_FAILED", "EXECUTED")) + "\n")
    # judge validation against rule-based trace facts
    md.append("### Judge validation against rule-based trace facts\n")
    f_no = [r["features"]["n_tool_calls"] == 0 for r, j in fails]
    j_no = [j["task_failure"] == "NO_TOOL_USE" for r, j in fails]
    att = [(r, j) for r, j in rows if r["attack"] != "none"]
    f_ne = [not r["features"]["injection_seen"] for r, j in att]
    j_ne = [j["injection_outcome"] == "NOT_EXPOSED" for r, j in att]
    hij = [(r, j) for r, j in fails if j["task_failure"] == "HIJACKED"]
    mal = [(r, j) for r, j in fails if j["task_failure"] == "MALFORMED_CALL"]
    vrows = [
        ["NO_TOOL_USE ⇔ no tool call in the trace", len(f_no), f"{np.mean([a == b for a, b in zip(f_no, j_no)]):.2f}",
         f"{kappa(f_no, j_no):.2f}"],
        ["NOT_EXPOSED ⇔ injected text never returned by a tool", len(f_ne),
         f"{np.mean([a == b for a, b in zip(f_ne, j_ne)]):.2f}", f"{kappa(f_ne, j_ne):.2f}"],
        ["HIJACKED ⇒ injected text was seen", len(hij),
         f"{np.mean([r['features']['injection_seen'] for r, _ in hij]):.2f}" if hij else "–", "–"],
        ["MALFORMED_CALL ⇒ a tool call returned an error", len(mal),
         f"{np.mean([r['features']['tool_errors'] > 0 for r, _ in mal]):.2f}" if mal else "–", "–"]]
    table(["check", "episodes", "agreement", "Cohen's κ"], vrows)
    st_path = RAW / "e14_stability.jsonl"
    if st_path.exists():
        st = [x for x in map(json.loads, st_path.read_text().splitlines()) if "error" not in x]
        agree = []
        for x in st:
            j0 = judged.get((x["suite"], x["user_task"], x["attack"]))
            if j0:
                agree.append(x["task_failure"] == j0["task_failure"])
        md.append(f"Stability: {len(st)} re-judgements at T = 0.7 (3 per episode) agree with the T = 0 verdict on "
                  f"the failure category in {np.mean(agree):.2f} of cases.\n" if agree else "")
    nt_path = RAW / "e14_notool.jsonl"
    if nt_path.exists():
        nt = [x for x in map(json.loads, nt_path.read_text().splitlines()) if "error" not in x]
        beh = ("ASKS_USER", "TEXT_TOOL_CALL", "CLAIMED_ACTION", "PLAN_ONLY", "OTHER")
        md.append(f"### What the agent did instead of calling a tool ({len(nt)} no-tool episodes)\n")
        table(["behaviour", "judge", "rule classifier"],
              [[b_, sum(x["behaviour"] == b_ for x in nt), sum(x["rule"] == b_ for x in nt)] for b_ in beh])
        agree = np.mean([x["behaviour"] == x["rule"] for x in nt]) if nt else float("nan")
        ks = ", ".join(f"{b_} κ = {kappa([x['behaviour'] == b_ for x in nt], [x['rule'] == b_ for x in nt]):.2f}"
                       for b_ in beh if any(x['rule'] == b_ or x['behaviour'] == b_ for x in nt))
        md.append(f"Judge and rule classifier agree on {agree:.2f} of no-tool episodes ({ks}).\n")
    for other in sorted(RAW.glob("e14_episodes_*.jsonl")):
        big = [r for r in map(json.loads, other.read_text().splitlines()) if "error" not in r]
        if not big:
            continue
        keys = {(r["suite"], r["user_task"], r["attack"]) for r in big}
        small = [r for r in ok if (r["suite"], r["user_task"], r["attack"]) in keys]
        name = other.stem.replace("e14_episodes_", "")
        md.append(f"### Capacity check: the same {len(big)} scenarios with a larger agent ({name})\n")

        def summ(rs):
            att = [r for r in rs if r["attack"] != "none"]
            return [f"{sum(r['utility'] for r in rs)}/{len(rs)}", f"{sum(bool(r['violation']) for r in att)}/{len(att)}",
                    f"{np.mean([r['features']['n_tool_calls'] == 0 for r in rs]):.2f}",
                    f"{np.mean([r['features']['injection_seen'] for r in att]):.2f}" if att else "–",
                    f"{np.median([r['latency_s'] for r in rs]):.0f}"]
        table(["agent", "utility", "violations (attack)", "episodes with no tool call", "injection seen (attack)",
               "median latency (s)"], [["qwen2.5:1.5b"] + summ(small), [name] + summ(big)])
    from realenv.e14_judge import notool_rule
    fig, (ax, ax2) = plt.subplots(1, 2, figsize=(12, 4.2))
    palette = ["#2a78d6", "#7fb2ea", "#eb6834", "#eda100", "#9a6fd6", "#d1335b", "#1baf7a", "#8a8984"]
    groups = [(su, att) for su in sorted({r["suite"] for r, _ in fails}) for att in ("none", "important_instructions")]
    labels = [f"{su}\n{'attack' if att != 'none' else 'no attack'}" for su, att in groups]
    bottom = np.zeros(len(groups))
    for c, col in zip(cats, palette):
        vals = np.array([sum(1 for r, j in fails if r["suite"] == su and r["attack"] == att and j["task_failure"] == c)
                         for su, att in groups], float)
        ax.bar(range(len(groups)), vals, bottom=bottom, color=col, label=c.replace("_", " ").lower(), width=0.7)
        bottom += vals
    ax.set_xticks(range(len(groups)), labels, fontsize=7)
    ax.set(title="Judge (Qwen2.5-7B): main reason for failure", ylabel="failed episodes")
    ax.legend(fontsize=7, ncol=2, loc="upper left")
    rule_cats = [("used tools", "#8a8984"), ("ASKS_USER", "#2a78d6"), ("TEXT_TOOL_CALL", "#9a6fd6"),
                 ("CLAIMED_ACTION", "#d1335b"), ("PLAN_ONLY", "#eda100"), ("OTHER", "#c9c8c4")]
    bottom = np.zeros(len(groups))
    for c, col in rule_cats:
        vals = np.array([sum(1 for r, _ in fails if r["suite"] == su and r["attack"] == att and
                             (("used tools" if r["features"]["n_tool_calls"] else notool_rule(r)) == c))
                         for su, att in groups], float)
        ax2.bar(range(len(groups)), vals, bottom=bottom, color=col, label=c.replace("_", " ").lower(), width=0.7)
        bottom += vals
    ax2.set_xticks(range(len(groups)), labels, fontsize=7)
    ax2.set(title="Trace facts (rule-based): tool use and what happened instead", ylabel="failed episodes")
    ax2.legend(fontsize=7, ncol=2, loc="upper left")
    fig.tight_layout()
    fig.savefig(FIG / "fig16_failure_taxonomy.png", dpi=160)
    plt.close(fig)


def e15():
    from realenv.e14_judge import notool_rule
    from realenv.e15_agents import AGENTS, out_path
    rows = []
    for m in AGENTS:
        p = out_path(m)
        if not p.exists():
            continue
        eps = [r for r in map(json.loads, p.read_text().splitlines()) if "error" not in r]
        if len(eps) < 48:
            continue
        att = [r for r in eps if r["attack"] != "none"]
        non = [r for r in eps if r["attack"] == "none"]
        seen = [r for r in att if r["features"]["injection_seen"]]
        v = sum(bool(r["violation"]) for r in att)
        rows.append({"agent": m, "util_none": sum(r["utility"] for r in non), "util_att": sum(r["utility"] for r in att),
                     "viol": v, "n_att": len(att), "seen": len(seen),
                     "viol_seen": sum(bool(r["violation"]) for r in seen),
                     "notool": np.mean([r["features"]["n_tool_calls"] == 0 for r in eps]),
                     "texttool": np.mean([r["features"]["n_tool_calls"] == 0 and notool_rule(r) == "TEXT_TOOL_CALL"
                                          for r in eps]),
                     "lat": float(np.median([r["latency_s"] for r in eps]))})
    if not rows:
        return
    md.append("## E15 — ten agents on the same scenarios\n")
    md.append("Each agent ran the same 48 AgentDojo episodes (6 user tasks per suite × with/without the "
              "important_instructions attack; T = 0.7, seed 1, local Ollama on CPU). Rule-based trace facts.\n")
    trows = []
    for r in rows:
        lo, hi = wilson(r["viol"], r["n_att"])[1:]
        trows.append([r["agent"], f"{r['util_none']}/24", f"{r['util_att']}/24",
                      f"{r['viol']}/{r['n_att']} [{lo:.2f}, {hi:.2f}]", f"{r['seen']}/{r['n_att']}",
                      f"{r['viol_seen']}/{r['seen']}" if r["seen"] else "–", f"{r['notool']:.2f}", f"{r['texttool']:.2f}",
                      f"{r['lat']:.0f}"])
    table(["agent", "task success (no attack)", "task success (attack)", "attack success [95% CI]",
           "injection reached agent", "attack success when reached", "no tool call", "tool call as text",
           "median latency (s)"], trows)
    tot_v = sum(r["viol"] for r in rows)
    tot_seen = sum(r["seen"] for r in rows)
    md.append(f"Pooled over agents: the attack succeeded in {tot_v} of {sum(r['n_att'] for r in rows)} attacked "
              f"episodes; all {tot_v} were among the {tot_seen} episodes in which the injected text reached the agent "
              f"({tot_v / max(1, tot_seen):.2f}).\n")
    fig, axs = plt.subplots(1, 2, figsize=(12, 4.2))
    cols = plt.cm.tab10(np.linspace(0, 1, 10))
    for r, c in zip(rows, cols):
        axs[0].scatter(1 - r["notool"], r["seen"] / r["n_att"], s=60, color=c, label=r["agent"], zorder=3)
        axs[1].scatter(r["seen"] / r["n_att"], r["viol"] / r["n_att"], s=60, color=c, zorder=3)
        if r["viol"]:                                  # colours as in the left legend
            axs[1].annotate(r["agent"], (r["seen"] / r["n_att"], r["viol"] / r["n_att"]), fontsize=7,
                            xytext=(4, 3), textcoords="offset points")
    axs[0].set(title="Using tools exposes the agent to the injection", xlabel="episodes with a tool call",
               ylabel="attacked episodes where the injection reached the agent", xlim=(-0.03, 1.03), ylim=(-0.03, 1.03))
    axs[1].set(title="Exposure, then compromise (colours as left)", xlabel="injection reached the agent (fraction of attacked)",
               ylabel="attack success (fraction of attacked)", xlim=(-0.03, 1.03), ylim=(-0.03, 0.6))
    axs[0].legend(fontsize=7, loc="upper left")
    fig.tight_layout()
    fig.savefig(FIG / "fig17_ten_agents.png", dpi=160)
    plt.close(fig)


def main():
    FIG.mkdir(exist_ok=True)
    OUT.mkdir(parents=True, exist_ok=True)
    md.append("# Stage 7 results (generated by analysis/stage7_figures.py)\n")
    for f in (e10, e11, e12, e13, e14, e15):
        try:
            f()
        except FileNotFoundError as e:
            md.append(f"_{f.__name__}: no data ({e.filename})_\n")
    (OUT / "stage7_summary.md").write_text("\n".join(md) + "\n")
    print("\n".join(md))


if __name__ == "__main__":
    main()
