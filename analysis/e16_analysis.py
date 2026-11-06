"""E16 analysis: does a weighted graph of LLM judges beat its best member?

Bipartite graph: judges on one side, (episode, question) items on the other; an edge is a judge's
true/false vote, and its weight is the judge's reliability on that question, learned on the
calibration split only. Aggregators compared on the held-out test split:

    single     each judge alone
    best       the judge with the highest calibration accuracy on that question
    majority   unweighted vote
    weighted   log-odds weights w = log(acc / (1 - acc))           (Nitzan & Paroush 1982)
    bayes      class-conditional weights from sensitivity/specificity plus the base rate
               (supervised Dawid-Skene / naive Bayes)
    ds-em      unsupervised Dawid-Skene EM on all items, no labels at all

An abstention (invalid output, error) is no vote; a single judge's abstention predicts the
calibration base-rate class. Ties predict the base-rate class.

    python3 -I analysis/e16_analysis.py    -> results/processed/e16_summary.md, figures/fig18_*.png
"""

import json
import math
import pathlib
import random

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parents[1]
RAW = ROOT / "results" / "raw"
OUT = ROOT / "results" / "processed" / "e16_summary.md"
FIG = ROOT / "figures"
QUESTIONS = ("TOOL", "TOOL_ERROR", "EXPOSED", "TASK_DONE", "HIJACKED")
JUDGES = ("qwen2.5:7b", "smollm2:1.7b", "deepseek-r1:7b", "gpt-oss:20b")
SHORT = {"qwen2.5:7b": "Qwen2.5-7B", "smollm2:1.7b": "SmolLM2-1.7B", "deepseek-r1:7b": "DeepSeek-R1-7B",
         "gpt-oss:20b": "gpt-oss-20b"}
METHODS = ("best", "majority", "weighted", "bayes", "ds-em")
B = 2000


def load():
    sample = {r["id"]: r for r in map(json.loads, (RAW / "e16_sample.jsonl").read_text().splitlines())}
    votes = {}
    for j in JUDGES:
        p = RAW / f"e16_votes_{j.replace(':', '-')}.jsonl"
        if p.exists():
            for line in p.read_text().splitlines():
                d = json.loads(line)
                votes.setdefault(j, {})[d["id"]] = d
    return sample, votes


def items(sample, split, q):
    return [i for i, r in sample.items() if r["split"] == split and r["truth"][q] is not None]


def vote(votes, j, i, q):
    d = votes.get(j, {}).get(i)
    v = d["answers"].get(q) if d else None
    return v if isinstance(v, bool) else None


def clip(p, eps=1e-3):
    return min(1 - eps, max(eps, p))


def fit(sample, votes, judges, q):
    """Calibration-split reliabilities, Laplace-smoothed."""
    cal = items(sample, "cal", q)
    prior = (sum(sample[i]["truth"][q] for i in cal) + 1) / (len(cal) + 2)
    stats = {}
    for j in judges:
        tp = fn = tn = fp = 0
        for i in cal:
            v, t = vote(votes, j, i, q), sample[i]["truth"][q]
            if v is None:
                continue
            tp += v and t
            fn += (not v) and t
            tn += (not v) and (not t)
            fp += v and (not t)
        n = tp + fn + tn + fp
        stats[j] = {"acc": (tp + tn + 1) / (n + 2), "sens": (tp + 1) / (tp + fn + 2), "spec": (tn + 1) / (tn + fp + 2),
                    "n": n, "abstain": len(cal) - n}
    return prior, stats


def dawid_skene(sample, votes, judges, q, iters=50):
    """Unsupervised binary Dawid-Skene on every item with a truth slot (labels never read)."""
    ids = [i for i, r in sample.items() if r["truth"][q] is not None]
    post = {}
    for i in ids:                                  # initialise with the majority vote
        vs = [v for j in judges if (v := vote(votes, j, i, q)) is not None]
        post[i] = (sum(vs) + 0.5) / (len(vs) + 1)
    for _ in range(iters):
        prior = clip(sum(post.values()) / len(post))
        sens, spec = {}, {}
        for j in judges:
            a = b = c = d = 1e-2
            for i in ids:
                v = vote(votes, j, i, q)
                if v is None:
                    continue
                a += post[i] * v
                b += post[i]
                c += (1 - post[i]) * (not v)
                d += 1 - post[i]
            sens[j], spec[j] = clip(a / b), clip(c / d)
        for i in ids:
            l1, l0 = math.log(prior), math.log(1 - prior)
            for j in judges:
                v = vote(votes, j, i, q)
                if v is None:
                    continue
                l1 += math.log(sens[j] if v else 1 - sens[j])
                l0 += math.log(1 - spec[j] if v else spec[j])
            post[i] = 1 / (1 + math.exp(l0 - l1))
    return {i: post[i] > 0.5 for i in ids}, sens, spec


def predict(method, sample, votes, judges, q, prior, stats, ds):
    base = prior >= 0.5
    test = items(sample, "test", q)
    out = {}
    for i in test:
        vs = {j: vote(votes, j, i, q) for j in judges}
        if method in judges:
            out[i] = base if vs[method] is None else vs[method]
        elif method == "best":
            jb = max(judges, key=lambda j: stats[j]["acc"])
            out[i] = base if vs[jb] is None else vs[jb]
        elif method == "majority":
            s = sum(1 if v else -1 for v in vs.values() if v is not None)
            out[i] = base if s == 0 else s > 0
        elif method == "weighted":
            s = sum((1 if v else -1) * math.log(clip(stats[j]["acc"]) / (1 - clip(stats[j]["acc"])))
                    for j, v in vs.items() if v is not None)
            out[i] = base if s == 0 else s > 0
        elif method == "bayes":
            s = math.log(prior / (1 - prior))
            for j, v in vs.items():
                if v is None:
                    continue
                se, sp = clip(stats[j]["sens"]), clip(stats[j]["spec"])
                s += math.log(se / (1 - sp)) if v else math.log((1 - se) / sp)
            out[i] = s > 0
        elif method == "ds-em":
            out[i] = ds[i]
    return out


def kappa(pairs):
    n = len(pairs)
    if not n:
        return float("nan")
    po = sum(p == t for p, t in pairs) / n
    pp, pt = sum(p for p, _ in pairs) / n, sum(t for _, t in pairs) / n
    pe = pp * pt + (1 - pp) * (1 - pt)
    return (po - pe) / (1 - pe) if pe < 1 else float("nan")


def bacc(pairs):
    pos = [p for p, t in pairs if t]
    neg = [not p for p, t in pairs if not t]
    parts = [sum(x) / len(x) for x in (pos, neg) if x]
    return sum(parts) / len(parts) if parts else float("nan")


def boot(pairs_by_ep, stat, rng):
    """Percentile CI, resampling episodes (all items of an episode move together)."""
    eps = list(pairs_by_ep)
    vals = []
    for _ in range(B):
        res = [x for e in (rng.choice(eps) for _ in eps) for x in pairs_by_ep[e]]
        v = stat(res)
        if not math.isnan(v):
            vals.append(v)
    vals.sort()
    return vals[int(0.025 * len(vals))], vals[int(0.975 * len(vals)) - 1]


def main():
    rng = random.Random(16)
    sample, votes = load()
    judges = [j for j in JUDGES if j in votes]
    complete = {i for i in sample if all(i in votes[j] for j in judges)}
    sample = {i: r for i, r in sample.items() if i in complete}
    lines = ["# E16: a weighted graph of LLM judges", "",
             f"Judges: {', '.join(SHORT[j] for j in judges)}. Episodes judged by every judge: {len(sample)} "
             f"({sum(r['split'] == 'cal' for r in sample.values())} calibration, "
             f"{sum(r['split'] == 'test' for r in sample.values())} test). Judges never saw AgentDojo's labels.", ""]
    per_q, weights, pooled = {}, {}, {m: {} for m in (*judges, *METHODS)}
    for q in QUESTIONS:
        prior, stats = fit(sample, votes, judges, q)
        ds, ds_sens, ds_spec = dawid_skene(sample, votes, judges, q)
        weights[q] = {j: math.log(clip(stats[j]["acc"]) / (1 - clip(stats[j]["acc"]))) for j in judges}
        test = items(sample, "test", q)
        per_q[q] = {"n": len(test), "pos": sum(sample[i]["truth"][q] for i in test), "stats": stats,
                    "best": max(judges, key=lambda j: stats[j]["acc"]), "ds": (ds_sens, ds_spec), "rows": {}}
        for m in (*judges, *METHODS):
            pred = predict(m, sample, votes, judges, q, prior, stats, ds)
            pairs = [(pred[i], sample[i]["truth"][q]) for i in test]
            for i in test:
                pooled[m].setdefault(i, []).append((pred[i], sample[i]["truth"][q]))
            per_q[q]["rows"][m] = {"acc": sum(p == t for p, t in pairs) / len(pairs), "bacc": bacc(pairs),
                                   "kappa": kappa(pairs)}

    lines += ["## Calibration reliabilities and graph weights", "",
              "Accuracy on the calibration split (Laplace-smoothed), abstentions in brackets; the edge weight is "
              "log(acc/(1-acc)).", "",
              "| Question | " + " | ".join(SHORT[j] for j in judges) + " |", "|---|" + "---|" * len(judges)]
    for q in QUESTIONS:
        st = per_q[q]["stats"]
        lines.append(f"| {q} | " + " | ".join(f"{st[j]['acc']:.2f} (w={weights[q][j]:+.2f}"
                                               + (f"; {st[j]['abstain']} abst." if st[j]['abstain'] else "") + ")"
                                               for j in judges) + " |")
    lines += ["", "## Held-out test split", "",
              "Balanced accuracy (mean of sensitivity and specificity) and Cohen's kappa against the truth.", "",
              "| Question (test n, positives) | " + " | ".join([SHORT[j] for j in judges] + list(METHODS)) + " |",
              "|---|" + "---|" * (len(judges) + len(METHODS))]
    for q in QUESTIONS:
        rows = per_q[q]["rows"]
        lines.append(f"| {q} ({per_q[q]['n']}, {per_q[q]['pos']}) | " + " | ".join(
            f"{rows[m]['bacc']:.2f} / {rows[m]['kappa']:.2f}" for m in (*judges, *METHODS)) + " |")
    lines += ["", "Cells: balanced accuracy / kappa. `best` = the judge with the highest calibration accuracy on "
              "that question: " + ", ".join(f"{q}: {SHORT[per_q[q]['best']]}" for q in QUESTIONS) + ".", ""]

    lines += ["## Pooled over all questions (test), 95% bootstrap CIs over episodes", "",
              "| Method | Accuracy | Balanced accuracy | Kappa |", "|---|---|---|---|"]
    summary = {}
    for m in (*judges, *METHODS):
        allp = [x for v in pooled[m].values() for x in v]
        acc = lambda ps: sum(p == t for p, t in ps) / len(ps)  # noqa: E731
        a, ba, k = acc(allp), bacc(allp), kappa(allp)
        ca, cb, ck = boot(pooled[m], acc, rng), boot(pooled[m], bacc, rng), boot(pooled[m], kappa, rng)
        summary[m] = {"acc": a, "bacc": ba, "kappa": k}
        lines.append(f"| {SHORT.get(m, m)} | {a:.3f} [{ca[0]:.3f}, {ca[1]:.3f}] | {ba:.3f} [{cb[0]:.3f}, {cb[1]:.3f}] "
                     f"| {k:.3f} [{ck[0]:.3f}, {ck[1]:.3f}] |")

    lines += ["", "## Paired differences in pooled accuracy (test), 95% bootstrap CIs", ""]
    eps = list(pooled["weighted"])
    for a_, b_ in (("weighted", "best"), ("weighted", "majority"), ("bayes", "best"), ("ds-em", "majority"),
                   ("weighted", "ds-em")):
        def diff(sel):
            pa = [x for e in sel for x in pooled[a_][e]]
            pb = [x for e in sel for x in pooled[b_][e]]
            return sum(p == t for p, t in pa) / len(pa) - sum(p == t for p, t in pb) / len(pb)
        d0 = diff(eps)
        ds_ = sorted(diff([rng.choice(eps) for _ in eps]) for _ in range(B))
        lines.append(f"- {a_} − {b_}: {d0:+.3f} [{ds_[int(0.025 * B)]:+.3f}, {ds_[int(0.975 * B) - 1]:+.3f}]")

    abst = {j: sum(1 for d in votes[j].values() if all(v is None for v in d["answers"].values())) for j in judges}
    secs = {j: sorted(d["seconds"] for d in votes[j].values())[len(votes[j]) // 2] for j in judges}
    lines += ["", "## Cost", "", "| Judge | Median seconds per episode (4 CPU cores) | Episodes with no valid answer |",
              "|---|---|---|"] + [f"| {SHORT[j]} | {secs[j]:.1f} | {abst[j]} |" for j in judges]
    OUT.write_text("\n".join(lines) + "\n")
    print("\n".join(lines))
    figures(judges, per_q, weights, summary)


def figures(judges, per_q, weights, summary):
    fig, axes = plt.subplots(1, 2, figsize=(12, 4.2), gridspec_kw={"width_ratios": [1, 1.5]})
    ax = axes[0]
    w = [[weights[q][j] for j in judges] for q in QUESTIONS]
    lim = max(abs(x) for r in w for x in r)
    im = ax.imshow(w, cmap="RdBu", vmin=-lim, vmax=lim)
    ax.set_xticks(range(len(judges)), [SHORT[j] for j in judges], rotation=25, ha="right")
    ax.set_yticks(range(len(QUESTIONS)), QUESTIONS)
    for r, row in enumerate(w):
        for c, x in enumerate(row):
            ax.text(c, r, f"{x:+.1f}", ha="center", va="center", fontsize=8)
    fig.colorbar(im, ax=ax, shrink=0.8, label="edge weight log(acc/(1−acc))")
    ax.set_title("Judge-graph weights (calibration split)")
    ax = axes[1]
    methods = (*judges, *METHODS)
    x = range(len(QUESTIONS))
    width = 0.8 / len(methods)
    colors = ["#9ecae1", "#c6dbef", "#fdd0a2", "#d9d9d9", "#636363", "#31a354", "#e6550d", "#756bb1", "#de2d26"]
    for k, m in enumerate(methods):
        ax.bar([i + k * width for i in x], [per_q[q]["rows"][m]["bacc"] for q in QUESTIONS], width,
               label=SHORT.get(m, m), color=colors[k % len(colors)])
    ax.set_xticks([i + 0.4 - width / 2 for i in x], QUESTIONS)
    ax.set_ylim(0.3, 1.02)
    ax.axhline(0.5, color="k", lw=0.6, ls=":")
    ax.set_ylabel("balanced accuracy (test)")
    ax.set_title("Single judges vs graph aggregators (held-out)")
    ax.legend(fontsize=7, ncol=3, loc="lower left")
    fig.tight_layout()
    fig.savefig(FIG / "fig18_judge_graph.png", dpi=160)


if __name__ == "__main__":
    main()
