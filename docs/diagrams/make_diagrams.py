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
    {"title": "P3 Eval + traces", "lines": ["golden set, gate, OTel"], "color": "blue"},
    {"title": "P4 Terraform", "lines": ["VPC, EKS, node groups"], "color": "purple"},
    {"title": "P5 LLM serving", "lines": ["KServe · CPU → GPU"], "color": "purple"},
    {"title": "P6 Gateway", "lines": ["LiteLLM, guardrails"], "color": "purple", "bold": True},
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


# 4. P3 evaluation and tracing --------------------------------------------------------------------
s = Svg(1240, 640, "P3: evaluation gate and tracing",
        "Top: every request is one trace, one span per step. Bottom: a change ships only if the golden set still passes")
s.group(24, 80, 1192, 210, "One request = one trace in Phoenix (OpenTelemetry). Each box is a span with its timing")
spans = [("guardrail_input", ["mask card, phone,", "account, SIN, email"], "red"),
         ("classify", ["label + confidence", "+ model version"], "blue"),
         ("policy_lookup", ["policy text for", "that label"], "teal"),
         ("llm", ["messages, tokens,", "prompt version"], "purple")]
s.box(44, 135, 150, 100, "POST /assist", ["claim text"], "gray")
for i, (title, lines, color) in enumerate(spans):
    x = 240 + i * 215
    s.box(x, 135, 180, 100, title, lines, color)
    s.arrow([(x - 33 if i else 196, 185), (x - 2, 185)])
s.box(1100, 135, 100, 100, "Reply", ["+ trace_id", "+ lineage"], "green")
s.arrow([(240 + 3 * 215 + 180, 185), (1098, 185)])
s.text(240 + 215 + 90, 262, "classifier service adds its own span (trace ID passed in the HTTP header)", size=12, color=MUTED)

s.group(24, 320, 1192, 230, "make eval [PROMPT=candidate]: like a CI preview environment")
s.box(44, 380, 200, 110, "Golden set", ["60 hand-written claims:", "clear, hard, PII,", "prompt injection"], "teal")
s.box(290, 380, 200, 110, "Assistant", ["candidate deployed,", "every claim sent", "(2 at a time)"], "amber")
s.box(536, 360, 230, 150, "Checks per reply", ["dispute type right?", "policy facts present?", "personal details repeated?",
      "refund promised?", "numbers invented?", "latency"], "blue")
s.box(812, 380, 180, 110, "LLM judge", ["counts only if it agrees", "with human labels", "(calibration set)"], "gray", dashed=True)
s.diamond(1100, 435, 80, 55, "Gate")
s.arrow([(244, 435), (288, 435)])
s.arrow([(490, 435), (534, 435)])
s.arrow([(766, 435), (810, 435)])
s.arrow([(992, 435), (1018, 435)])
s.text(1100, 520, "pass: ship · fail: exit 1", size=12, weight="700", color=MUTED)
s.arrow([(390, 380), (390, 300)], dashed=True, label="trace link per failing case", label_at=(480, 312), label_color=MUTED)
s.legend(30, 610, [("red", "Guardrail (masks before any model)"), ("blue", "Model / checks"), ("teal", "Data"), ("amber", "System under test")])
s.save("eval-and-tracing.svg")


# 5. Training data vs golden set ------------------------------------------------------------------
s = Svg(1240, 470, "Training data and the golden set never mix",
        "P2 builds the classifier from generated data. P3 tests the whole running system with claims nobody trained on")
s.group(24, 80, 1192, 140, "P2 training pipeline: \"is this model good enough to publish?\"")
s.box(44, 115, 220, 85, "Generated claims", ["CSV exports in S3", "(same generator for", "train, val and test)"], "teal")
s.box(320, 115, 220, 85, "Train + gate", ["scikit-learn vs PyTorch", "test macro-F1 0.99"], "amber")
s.box(596, 115, 220, 85, "Model v2 published", ["models/dispute-", "classifier/v2/"], "blue")
s.arrow([(264, 157), (318, 157)])
s.arrow([(540, 157), (594, 157)])
s.group(24, 250, 1192, 160, "P3 evaluation: \"does the whole system answer real-looking claims correctly and safely?\"")
s.box(44, 290, 220, 95, "Golden set", ["60 hand-written claims", "+ correct dispute type", "never used for training"], "teal", bold_border=True)
s.box(596, 290, 360, 95, "Running app (the candidate)", ["guardrail → classifier v2 → policy →", "prompt → LLM → reply"], "green")
s.box(1010, 290, 186, 95, "Score + gate", ["accuracy 0.67", "exit 0 or exit 1"], "amber")
s.arrow([(264, 337), (594, 337)], label="sent one by one", label_at=(430, 327), label_color=MUTED)
s.arrow([(956, 337), (1008, 337)])
s.arrow([(706, 200), (706, 288)], label="the model under test", label_at=(790, 238), label_color=MUTED)
s.text(620, 450, "0.99 on its own test vs 0.67 on the golden set: a test from the same source as the training data flatters the model",
       size=13, weight="700", color=C["red"][1])
s.save("train-vs-eval.svg")


# 6. Candidate test in CI -------------------------------------------------------------------------
s = Svg(1240, 560, "Where the candidate test runs in production: every pull request (P7)",
        "A change that can affect answers is deployed next to production, scored on the golden set, and merged only if the gate passes")
s.box(24, 110, 170, 95, "Pull request", ["prompt v2, classifier v3,", "bigger LLM, new policy"], "gray")
s.group(220, 80, 760, 160, "CI pipeline (GitHub Actions)")
s.box(240, 115, 160, 95, "1 Build", ["assistant image", "with the change"], "blue")
s.box(420, 115, 180, 95, "2 Preview env", ["temporary namespace", "pr-42 = the candidate"], "green")
s.box(620, 115, 160, 95, "3 Golden set", ["60 claims through", "the candidate"], "teal")
s.diamond(880, 162, 75, 50, "4 Gate")
s.arrow([(194, 157), (238, 157)])
s.arrow([(400, 162), (418, 162)])
s.arrow([(600, 162), (618, 162)])
s.arrow([(780, 162), (803, 162)])
s.box(1020, 110, 196, 95, "PR blocked", ["report attached:", "\"refund promises 10.7%\""], "red", dashed=True)
s.arrow([(955, 162), (1018, 157)], color=C["red"][1], label="exit 1", label_at=(985, 148))
s.box(780, 300, 200, 85, "Review + merge", ["to main"], "purple")
s.arrow([(880, 212), (880, 298)], label="exit 0", label_at=(905, 260), label_color=C["green"][1])
s.box(500, 300, 220, 85, "Argo CD (P7)", ["deploys main", "(GitOps)"], "purple")
s.arrow([(780, 342), (722, 342)])
s.box(220, 300, 220, 85, "Canary (P10)", ["5% of real traffic", "first, then 100%"], "amber")
s.arrow([(500, 342), (442, 342)])
s.box(24, 300, 150, 85, "Customers", ["production"], "green", bold_border=True)
s.arrow([(220, 342), (176, 342)])
s.text(510, 175 + 95, "step 5: delete the preview namespace (production was never touched)", size=12, color=MUTED)
s.box(220, 430, 760, 70, "Our laptop version: make eval PROMPT=x",
      ["same steps by hand: helm upgrade with the candidate → run_eval.py → exit 0/1 → trap puts v1 back"], "gray", dashed=True)
s.save("candidate-in-ci.svg")


# 7. P4 platform on AWS ---------------------------------------------------------------------------
s = Svg(1240, 920, "P4: what one terraform apply builds on AWS",
        "Built at the start of a session (make eks-up), destroyed at the end (make eks-down). Only the P0 bootstrap stays")
s.box(24, 110, 180, 110, "Your laptop", ["make eks-up / eks-down", "terraform + kubectl", "(kubectl → API)"], "gray")
s.box(24, 610, 180, 130, "P0 bootstrap", ["(never destroyed)", "Terraform state bucket", "budget alert $20 / $50", "GitHub OIDC role"], "gray", dashed=True)
s.arrow([(114, 220), (114, 608)], dashed=True, label="state: platform/", label_at=(62, 420), label_color=MUTED)
s.group(224, 80, 992, 790, "AWS account · us-east-1")
s.box(244, 115, 600, 95, "EKS control plane · Kubernetes 1.36 (run by AWS, $0.10/h)",
      ["API server: only your IP may connect · access entries", "Secrets encrypted with the KMS key · audit logs → CloudWatch"], "purple", title_size=14)
s.arrow([(204, 160), (242, 160)])
s.group(244, 235, 620, 615, "VPC 10.20.0.0/16 · 2 availability zones")
s.box(264, 275, 180, 70, "Public subnets", ["load balancers later (P5+)"], "gray", dashed=True, title_size=13)
s.box(584, 275, 260, 70, "NAT gateway", ["private nodes → internet (image pulls)"], "gray", title_size=13)
s.group(264, 370, 580, 465, "Private subnets (zones a + b): nodes and database, no public IPs")
s.arrow([(500, 210), (500, 408)], label="runs the nodes", label_at=(500, 360), label_color=MUTED)
s.box(284, 410, 260, 155, "system node group", ["2× t3.large · ON-DEMAND", "Argo CD", "CoreDNS, VPC CNI, EBS CSI,", "Pod Identity agent", "assistant + classifier (P5)"], "blue", bold_border=True)
s.box(564, 410, 260, 155, "llm node group", ["1–2× c7i.large · SPOT (~70% off)", "taint workload=llm:NoSchedule", "only pods that tolerate it:", "the LLM server (P5)"], "purple", bold_border=True)
s.arrow([(714, 408), (714, 347)], label="image pulls", label_at=(760, 385), label_color=MUTED)
s.box(284, 590, 260, 110, "gpu node group (off)", ["g4dn.xlarge spot · 0 → 1 nodes", "taint nvidia.com/gpu", "gpu_enabled = false until quota"], "gray", dashed=True)
s.box(564, 590, 260, 110, "RDS PostgreSQL 16", ["db.t4g.micro · MLflow's database", "port 5432 from nodes only", "encrypted, password in Secrets Mgr"], "teal")
s.arrow([(694, 565), (694, 588)])
s.text(554, 740, "VPC CNI: every pod gets a real VPC IP address, so the private subnets are big (/20 = 4,096 IPs each)", size=12, color=MUTED)
s.text(554, 765, "One NAT gateway saves $0.045/h; production uses one per zone", size=12, color=MUTED)
s.box(890, 250, 306, 100, "S3 buckets (versioned, KMS)", ["mlops: raw/, datasets/, mlflow/, argo/", "models: published models, llm/ weights"], "amber")
s.box(890, 375, 306, 85, "ECR registries", ["assistant, classifier, trainer, mlflow", "immutable tags · scan on push"], "amber")
s.box(890, 485, 306, 130, "IAM roles via Pod Identity", ["dispute/classifier → read models", "dispute/llm → read models/llm/", "mlops/trainer → write models", "mlops/mlflow → mlops/mlflow/  ·  no keys"], "red")
s.box(890, 640, 306, 80, "KMS key (ours)", ["encrypts S3, Secrets, RDS, ECR"], "green")
s.arrow([(844, 300), (888, 300)], label="S3", label_at=(866, 290), label_color=MUTED)
s.arrow([(844, 417), (888, 417)], label="pull", label_at=(866, 407), label_color=MUTED)
s.arrow([(824, 520), (888, 540)], label="role", label_at=(858, 518), label_color=MUTED)
s.legend(30, 895, [("blue", "Always-on compute (on-demand)"), ("purple", "Spot / AWS-managed"), ("amber", "Storage + images"), ("red", "Access (IAM)")])
s.save("p4-platform.svg")


# 8. P4 taints and tolerations ---------------------------------------------------------------------
s = Svg(1240, 470, "Where pods land: labels invite, taints repel",
        "nodeSelector = \"only run me on nodes with this label\" · taint = \"stay away unless you tolerate me\" (make eks-check)")
pods = [("wants-llm-node", ["nodeSelector node-role=llm", "toleration workload=llm"], "green"),
        ("ordinary", ["no nodeSelector", "no toleration"], "blue"),
        ("no-toleration", ["nodeSelector node-role=llm", "no toleration"], "red")]
for i, (title, lines, color) in enumerate(pods):
    s.box(40, 100 + i * 115, 280, 90, title, lines, color)
s.box(560, 90, 300, 110, "llm node", ["label node-role=llm", "TAINT workload=llm:NoSchedule", "spot c7i.large"], "purple", bold_border=True)
s.box(560, 225, 300, 90, "system nodes", ["label node-role=system", "no taint · on-demand t3.large"], "blue")
s.box(560, 340, 300, 90, "Pending (not scheduled)", ["no node is both labelled llm", "and willing to accept it"], "red", dashed=True)
s.arrow([(320, 145), (558, 145)], label="label matches + taint tolerated", label_at=(440, 135), label_color=C["green"][1])
s.arrow([(320, 260), (558, 270)], label="taint keeps it off the llm node", label_at=(440, 252), label_color=MUTED)
s.arrow([(320, 375), (558, 385)], color=C["red"][1], label="wants llm, but the taint repels it", label_at=(440, 368))
s.box(900, 120, 316, 280, "Why it matters", ["Expensive nodes (LLM, GPU) run only", "the workloads that need them.", "", "Without the taint, any pod could", "fill the GPU node and keep it", "alive (and billing) for nothing.", "", "Without the label, the LLM pod", "could land on a small system node."], "gray")
s.save("p4-node-placement.svg")


# 9. Environments in real projects ----------------------------------------------------------------
s = Svg(1240, 700, "How real projects handle environments",
        "Same code, different accounts and values. Each box with a dashed border is its own AWS account")
s.box(24, 100, 260, 110, "Git: the same code for every env", ["terraform modules (versioned)", "Helm charts (versioned)", "app images (built once)"], "gray")
for i, (env, color, note) in enumerate([("Dev account", "green", "anyone on the team can apply"),
                                        ("Staging account", "amber", "a copy of prod, for final tests"),
                                        ("Prod account", "red", "CI only, main branch + approval")]):
    x = 330 + i * 300
    s.group(x, 85, 280, 470, env)
    s.text(x + 140, 125, note, size=12, color=MUTED)
    s.box(x + 20, 140, 240, 60, "state bucket + CI role", ["bootstrap (created once)"], "gray", title_size=13)
    for j, (stack, lines) in enumerate([("network", ["VPC, subnets, NAT"]), ("eks", ["cluster, node groups"]),
                                        ("data", ["RDS, S3 (protected)"]), ("addons", ["Argo CD, monitoring"])]):
        y = 220 + j * 78
        s.box(x + 20, y, 240, 60, f"{stack} stack", [lines[0] + " · own state file"], color, title_size=13)
        if j:
            s.arrow([(x + 140, y - 18), (x + 140, y - 2)])
s.arrow([(284, 155), (328, 155)])
s.text(470, 590, "Each stack has its own state file: a bad apply on eks can't touch network or data.", size=13, color=INK, anchor="start")
s.text(470, 614, "A stack reads the one above it through SSM parameters, data sources or terraform_remote_state.", size=13, color=INK, anchor="start")
s.text(470, 638, "Dev credentials can't read or change anything in the prod account.", size=13, color=INK, anchor="start")
s.box(24, 250, 260, 150, "Shared accounts", ["management: billing, org rules", "security: audit logs from all", "shared services: ECR, CI runners"], "blue")
s.box(24, 440, 260, 115, "Promotion", ["the same image and module", "version moves dev → staging", "→ prod, after checks pass"], "purple")
s.save("environments.svg")


# 10. P5 on EKS: what runs where -----------------------------------------------------------------
s = Svg(1240, 760, "P5: serving and training on EKS, and what runs where",
        "Node groups by kind of work, namespaces by team, priorities decide who wins when the cluster is full")
cols = [("system nodes · 2× t3.large on-demand", "blue", 24, 400,
         [("assistant", "dispute · Helm chart · serving"), ("classifier (KServe)", "dispute · v2 from S3 · serving"),
          ("MLflow", "mlops · DB on RDS · serving"), ("Argo CD, Argo Workflows,", "KServe, cert-manager, add-ons")]),
        ("llm node · spot c5.large (11 types)", "purple", 444, 360,
         [("LLM (KServe)", "dispute · llama.cpp · Qwen 0.5B"), ("taint workload=llm", "only the LLM tolerates it"),
          ("Recreate strategy", "one replica fills the node")]),
        ("training node · spot m5.large (11 types)", "amber", 824, 392,
         [("pipeline step pods", "mlops · Argo · priority training"), ("taint workload=training", "only pipeline pods"),
          ("preempted by serving", "when serving needs the room")])]
for title, color, x, w, items in cols:
    s.group(x, 85, w, 330, title)
    for i, (t, line) in enumerate(items):
        s.box(x + 20, 120 + i * 72, w - 40, 60, t, [line], color, title_size=13)
s.box(24, 450, 300, 110, "S3 models bucket", ["dispute-classifier/v1, v2", "(published by the EKS pipeline)", "llm/…/model.gguf"], "teal")
s.box(350, 450, 300, 110, "KServe storage initializer", ["init container: downloads", "STORAGE_URI → /mnt/models", "with Pod Identity (no keys)"], "gray")
s.box(676, 450, 270, 110, "S3 mlops bucket", ["raw/, datasets/,", "mlflow/, argo/"], "teal")
s.box(972, 450, 244, 110, "RDS PostgreSQL", ["MLflow's database", "(MLflow: system nodes)", "password from Secrets Mgr"], "teal")
s.arrow([(324, 505), (348, 505)])
s.arrow([(500, 450), (500, 416)], label="before the model server starts", label_at=(600, 436), label_color=MUTED)
s.arrow([(1020, 416), (811, 448)], dashed=True)
s.group(24, 590, 1192, 130, "Teams (namespaces) · quotas · priorities")
s.box(44, 625, 360, 80, "disputes team", ["dispute: CPU 3, memory 3Gi", "mlops: CPU 2, memory 4Gi"], "green", title_size=13)
s.box(430, 625, 360, 80, "team-fraud (example 2nd team)", ["CPU 500m, memory 1Gi, GPU 0", "shared pipeline template, no S3 role yet"], "gray", title_size=13)
s.box(816, 625, 380, 80, "PriorityClasses", ["serving 100000: may preempt training", "training 1000: never preempts, retried"], "red", title_size=13)
s.save("p5-eks.svg")
