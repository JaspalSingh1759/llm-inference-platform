"""Draws the LLM inference platform diagrams as standalone SVGs with a shared style."""
import sys
from pathlib import Path
from xml.sax.saxutils import escape

OUT = Path(sys.argv[1])
OUT.mkdir(parents=True, exist_ok=True)

C = {  # fill, stroke
    "blue": ("#e8f0fe", "#4a7bd0"), "amber": ("#fef3e0", "#c98a1b"), "green": ("#e6f4ea", "#3b8a52"),
    "purple": ("#f1e8fd", "#7b52c7"), "red": ("#fde8e8", "#c0392b"), "gray": ("#f3f4f6", "#9ca3af"),
    "teal": ("#e0f5f5", "#1f8a8a"),
}
INK, MUTED = "#1f2937", "#4b5563"


class Svg:
    def __init__(self, w, h, title, subtitle=None):
        self.w, self.h, self.parts = w, h, []
        self.parts.append(f'<rect width="{w}" height="{h}" fill="#ffffff"/>')
        self.text(24, 34, title, size=20, weight="700", anchor="start")
        if subtitle:
            self.text(24, 56, subtitle, size=13, color=MUTED, anchor="start")

    def text(self, x, y, s, size=13, weight="400", color=INK, anchor="middle", italic=False):
        style = ' font-style="italic"' if italic else ""
        self.parts.append(f'<text x="{x}" y="{y}" font-size="{size}" font-weight="{weight}" fill="{color}" '
                          f'text-anchor="{anchor}"{style}>{escape(s)}</text>')

    def box(self, x, y, w, h, title, lines=(), color="blue", dashed=False, bold_border=False, title_size=15):
        fill, stroke = C[color]
        dash = ' stroke-dasharray="6 4"' if dashed else ""
        sw = 3 if bold_border else 1.6
        self.parts.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="10" fill="{fill}" '
                          f'stroke="{stroke}" stroke-width="{sw}"{dash}/>')
        n = 1 + len(lines)
        line_h = 17
        top = y + h / 2 - (n - 1) * line_h / 2 + 5
        self.text(x + w / 2, top, title, size=title_size, weight="700")
        for i, line in enumerate(lines, start=1):
            self.text(x + w / 2, top + i * line_h, line, size=12, color=MUTED)

    def diamond(self, cx, cy, hw, hh, label, color="amber"):
        fill, stroke = C[color]
        pts = f"{cx},{cy - hh} {cx + hw},{cy} {cx},{cy + hh} {cx - hw},{cy}"
        self.parts.append(f'<polygon points="{pts}" fill="{fill}" stroke="{stroke}" stroke-width="1.6"/>')
        self.text(cx, cy + 5, label, size=13, weight="700")

    def group(self, x, y, w, h, label):
        self.parts.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="14" fill="none" '
                          f'stroke="#9ca3af" stroke-width="1.2" stroke-dasharray="5 5"/>')
        self.text(x + 14, y + 20, label, size=12, weight="700", color=MUTED, anchor="start")

    def arrow(self, points, color="#6b7280", dashed=False, label=None, label_at=None, label_color=None):
        d = "M" + " L".join(f"{x},{y}" for x, y in points)
        dash = ' stroke-dasharray="6 4"' if dashed else ""
        mid = "arrowred" if color == C["red"][1] else "arrow"
        self.parts.append(f'<path d="{d}" fill="none" stroke="{color}" stroke-width="1.8"{dash} '
                          f'marker-end="url(#{mid})"/>')
        if label:
            lx, ly = label_at
            self.text(lx, ly, label, size=12, weight="700", color=label_color or color)

    def legend(self, x, y, items):
        for i, (color, label) in enumerate(items):
            fill, stroke = C[color]
            xx = x + i * 260
            self.parts.append(f'<rect x="{xx}" y="{y - 11}" width="16" height="16" rx="4" fill="{fill}" stroke="{stroke}"/>')
            self.text(xx + 24, y + 2, label, size=12, color=MUTED, anchor="start")

    def save(self, name):
        defs = ('<defs>'
                '<marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="8" markerHeight="8" orient="auto-start-reverse">'
                '<path d="M0,0 L10,5 L0,10 z" fill="#6b7280"/></marker>'
                f'<marker id="arrowred" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="8" markerHeight="8" orient="auto-start-reverse">'
                f'<path d="M0,0 L10,5 L0,10 z" fill="{C["red"][1]}"/></marker>'
                '</defs>')
        svg = (f'<svg xmlns="http://www.w3.org/2000/svg" width="{self.w}" height="{self.h}" viewBox="0 0 {self.w} {self.h}" '
               f'font-family="-apple-system, Segoe UI, Helvetica, Arial, sans-serif">{defs}' + "".join(self.parts) + "</svg>\n")
        (OUT / name).write_text(svg, encoding="utf-8")


def snake(s, steps, y1, y2, w=180, h=78, gap=35, x0=30, per_row=5):
    """Two rows: the first per_row steps left→right on top, the rest right→left below. Returns box positions."""
    n = per_row
    xs = [x0 + i * (w + gap) for i in range(n)]
    pos = []
    for i, step in enumerate(steps):
        x, y = (xs[i], y1) if i < n else (xs[2 * n - 1 - i], y2)
        s.box(x, y, w, h, step["title"], step.get("lines", ()), step.get("color", "blue"),
              dashed=step.get("dashed", False), bold_border=step.get("bold", False))
        pos.append((x, y))
    for i in range(len(steps) - 1):
        (x, y), (nx, ny) = pos[i], pos[i + 1]
        if i < n - 1:
            s.arrow([(x + w, y + h / 2), (nx - 2, ny + h / 2)])
        elif i == n - 1:
            s.arrow([(x + w / 2, y + h), (nx + w / 2, ny - 2)])
        else:
            s.arrow([(x, y + h / 2), (nx + w + 2, ny + h / 2)], dashed=steps[i + 1].get("dashed", False))
    return pos, w, h


# 1. Architecture --------------------------------------------------------------------------------
s = Svg(1260, 800, "LLM inference platform on Kubernetes: what we build",
        "One platform, two kinds of model: an LLM (CPU now, GPU when quota allows) and a classic ML model (scikit-learn)")
# Users + request flow (top)
s.box(20, 90, 170, 80, "Client", ["POST /assist", "a customer claim"], "gray")
s.arrow([(190, 130), (238, 130)])
s.group(230, 70, 1020, 470, "EKS cluster (Terraform) · deployed by Argo CD from Git")
s.box(250, 95, 190, 90, "Assistant API", ["FastAPI · the app", "orchestrates the steps"], "amber", bold_border=True)
s.box(490, 95, 190, 90, "Guardrails", ["PII masking in + out", "prompt-injection check"], "red")
s.arrow([(440, 140), (488, 140)])
s.box(730, 95, 210, 90, "LLM gateway", ["LiteLLM · routing, keys,", "rate limits, cost, fallback"], "purple")
s.arrow([(680, 140), (728, 140)])
s.box(990, 95, 240, 90, "Amazon Bedrock", ["fallback model", "(when our LLM is down/busy)"], "blue", dashed=True)
s.arrow([(940, 125), (988, 125)], dashed=True, label="fallback", label_at=(964, 117), label_color=MUTED)
# Serving row
s.group(250, 215, 520, 170, "KServe (model serving)")
s.box(270, 250, 230, 110, "Classifier", ["InferenceService · CPU", "scikit-learn, retrained", "by the training pipeline"], "green")
s.box(520, 250, 230, 110, "LLM", ["InferenceService", "now: llama.cpp on CPU", "later: vLLM on GPU"], "green", bold_border=True)
s.arrow([(330, 185), (330, 248)], label="1 classify", label_at=(370, 212), label_color=MUTED)
s.arrow([(835, 185), (835, 220), (690, 220), (690, 248)], label="2 generate", label_at=(870, 212), label_color=MUTED)
s.box(1030, 250, 200, 110, "Policy snippets", ["one per dispute type", "(tiny RAG: picked", "by the classifier)"], "gray")
s.box(800, 250, 200, 110, "Model cache", ["weights from S3", "on a volume → fast", "cold start"], "blue")
s.arrow([(800, 305), (752, 305)], dashed=True)
# Nodes row
s.box(270, 410, 230, 100, "System node group", ["app, gateway,", "monitoring, classifier"], "gray")
s.box(520, 410, 230, 100, "LLM node group", ["now: c7i.large spot (CPU)", "later: g4dn T4 GPU"], "gray", bold_border=True)
s.box(800, 410, 200, 100, "Autoscaling", ["KEDA on LLM queue", "more LLM nodes on load"], "green")
s.box(1030, 410, 200, 100, "Prometheus + Grafana", ["LLM serving metrics,", "tokens, cost, SLOs"], "green")
# LLMOps loop (bottom)
s.group(20, 570, 1230, 175, "LLMOps loop (GitHub Actions + Git)")
loop = [("Change", ["prompt, model or code", "in a PR"], "teal"),
        ("Eval gate", ["golden set: accuracy,", "faithfulness, safety"], "amber"),
        ("Build + scan", ["image → ECR", "model → S3"], "purple"),
        ("GitOps commit", ["new version in", "env values"], "purple"),
        ("Canary", ["10% traffic → metrics", "+ online eval → 100%"], "green"),
        ("Trace + feedback", ["OpenTelemetry → Phoenix", "bad answers → golden set"], "blue")]
for i, (t, l, c) in enumerate(loop):
    x = 40 + i * 202
    s.box(x, 610, 180, 95, t, l, c, bold_border=(c == "amber"))
    if i < 5:
        s.arrow([(x + 180, 657), (x + 200, 657)])
s.arrow([(1130, 705), (1130, 725), (130, 725), (130, 707)], dashed=True)
s.text(630, 740, "every bad answer found in production becomes a new test case", size=11, color=MUTED)
s.legend(30, 780, [("amber", "Our app / gates"), ("green", "Serving + scaling"), ("purple", "Gateway + delivery"), ("blue", "AWS / tracing")])
s.save("architecture.svg")


# 2. Phases ---------------------------------------------------------------------------------------
s = Svg(1240, 480, "Fourteen phases, four milestones", "Each phase ends with something working and one interview story. Thick border = next")
steps = [
    {"title": "P0 Foundations", "lines": ["budget, OIDC, quota"], "color": "blue"},
    {"title": "P1 Local LLM", "lines": ["kind + llama.cpp + app"], "color": "blue"},
    {"title": "P2 Training", "lines": ["Argo, MLflow, gate"], "color": "blue"},
    {"title": "P3 Eval + traces", "lines": ["golden set, gate, OTel"], "color": "blue", "bold": True},
    {"title": "P4 Terraform", "lines": ["VPC, EKS, node groups"], "color": "purple"},
    {"title": "P5 LLM serving", "lines": ["KServe · CPU → GPU"], "color": "purple"},
    {"title": "P6 Gateway", "lines": ["LiteLLM, guardrails"], "color": "purple"},
    {"title": "P7 CI/CD", "lines": ["eval gate → GitOps"], "color": "green"},
    {"title": "P8 Observe", "lines": ["TTFT, GPU, tokens"], "color": "green"},
    {"title": "P9 Scale + cost", "lines": ["KEDA, Karpenter, k6"], "color": "green"},
    {"title": "P10 Rollouts", "lines": ["canary, online eval"], "color": "amber"},
    {"title": "P11 Security", "lines": ["IAM, policies, PII"], "color": "amber"},
    {"title": "P12 Incidents", "lines": ["7 drills, runbooks"], "color": "amber"},
]
snake(s, steps, 90, 290, w=150, h=78, gap=22, x0=24, per_row=7)
s.legend(30, 420, [("blue", "M1: works on a laptop (free)"), ("purple", "M2: LLM inference on EKS"), ("green", "M3: automated + observable"), ("amber", "M4: production-grade")])
s.text(1216, 462, "Optional P13: the same LLM on a SageMaker endpoint, to compare", size=12, color=MUTED, anchor="end")
s.save("phases.svg")


# 3. P2 training pipeline -------------------------------------------------------------------------
s = Svg(1240, 690, "P2 training pipeline: raw data in, a served model version out",
        "Each step is a pod in an Argo Workflow. A failed step stops the run, and production keeps its current model")
s.box(24, 115, 170, 100, "Raw data drop", ["SeaweedFS (S3 later)", "raw/claims-<month>.csv", "from the data team"], "teal")
s.box(24, 250, 170, 90, "Trigger", ["now: make train", "later: new raw file,", "drift alert, or cron"], "gray", dashed=True)
s.arrow([(194, 165), (232, 165)])
s.group(214, 80, 1002, 260, "Argo Workflow \"train-classifier\": one pod per step, all from the trainer image")
steps = [("0 Prepare", ["raw CSV → clean,", "dedupe, split, version"], "teal"),
         ("1 Validate", ["schema, leakage,", "classes, file hashes"], "amber"),
         ("2 Train + gate", ["scikit-learn vs PyTorch,", "best on val, thresholds"], "amber"),
         ("3 Compare", ["vs champion; same", "data+code = nothing new"], "amber"),
         ("4 Publish", ["only if promoted:", "model + metadata → store"], "purple")]
stops = [("stop: unreadable", "bad file / columns"), ("stop: bad data", "nothing is trained"),
         ("stop: gate failed", "saved, not registered"), ("stop: not better", "prod model unchanged")]
W, STEP = 176, 196
for i, (title, lines, color) in enumerate(steps):
    x = 234 + i * STEP
    s.box(x, 115, W, 100, title, lines, color, bold_border=(color == "amber"))
    if i < 4:
        s.arrow([(x + W, 165), (x + STEP - 2, 165)])
        s.arrow([(x + 50, 215), (x + 50, 248)], color=C["red"][1], dashed=True)
        s.box(x, 250, 150, 62, stops[i][0], [stops[i][1]], "red", dashed=True, title_size=13)
s.box(560, 390, 440, 95, "MLflow: tracking + registry",
      ["every run and candidate: params, scores, dataset, commit", "aliases challenger / champion · PostgreSQL database"], "blue")
tx, cx = 234 + 2 * STEP + 163, 234 + 3 * STEP + 163
s.arrow([(tx, 215), (tx, 388)], dashed=True, label="register challenger", label_at=(tx - 54, 368), label_color=MUTED)
s.arrow([(cx, 215), (cx, 388)], dashed=True, label="promote champion", label_at=(cx - 54, 368), label_color=MUTED)
px = 234 + 4 * STEP + W // 2
s.box(1030, 390, 186, 95, "Model store", ["SeaweedFS (S3 later)", "models/dispute-", "classifier/v<N>/"], "blue")
s.arrow([(px, 215), (px, 388)])
s.box(1010, 535, 206, 90, "GitOps commit", ["classifier model", "version = v<N> (PR)"], "purple")
s.arrow([(px, 485), (px, 533)])
s.box(530, 535, 360, 90, "Classifier pod (serving)",
      ["init container downloads v<N> from the store;", "server checks sha256 + framework, then serves"], "green", bold_border=True)
s.arrow([(1010, 580), (892, 580)], label="Helm / Argo CD", label_at=(950, 570), label_color=MUTED)
s.box(230, 535, 250, 90, "Assistant", ["POST /assist gets dispute", "types from the new model"], "amber")
s.arrow([(530, 580), (482, 580)])
s.legend(30, 668, [("amber", "Gates (a pod that can stop the run)"), ("teal", "Data in + data processing"), ("blue", "Storage + registry"), ("red", "Where a bad run stops")])
s.save("training-pipeline.svg")
