# cv-optimizer

A small Python app that takes your CV and a job offer, and produces a CV
**deeply aligned** to that offer — without inventing anything, optimized
for ATS systems and for a human recruiter.

You pick which LLM provider to use:

- **Claude** (Anthropic)
- **ChatGPT** (OpenAI)
- **Gemini** (Google)
- **DeepSeek**

`cvo setup` walks you through picking a provider and pasting its API key.
The key is saved in `.env` (gitignored, never committed).

## What it does

1. **Parses your CV PDF into structured JSON**. Optional — you can also
   feed it a JSON directly.
2. **Analyzes the offer** and extracts: hard skills, soft skills, exact
   ATS keywords, key responsibilities, valued metrics, seniority, and tone.
3. **Aligns each experience** with strict anti-fabrication rules:
   - Rewrites bullets in `VERB + WHAT + IMPACT` form.
   - Inserts ATS keywords **only when your experience supports them**.
   - Orders bullets from most to least relevant.
   - Returns a 0–100 alignment score per experience.
4. **Rewrites the professional summary** aligned to the offer.
5. **Reorders your skills**, putting offer-matching ones first and flagging
   the ones you are missing.
6. **Generates** ATS-friendly Markdown + structured JSON of the optimized CV
   (and optionally PDF / DOCX) plus an audit report.

### Anti-fabrication rule

A strict rule: **never invent technologies, metrics, or achievements that
are not in your original experience**. If the offer asks for Kubernetes and
you don't have it, the model will NOT add it — it will flag it in the
report under "skills the offer asks for and you do NOT declare".

## Install

### One-shot setup

```bash
git clone <your-repo> cv-optimizer
cd cv-optimizer
./setup.sh                # creates venv, installs deps, runs `cvo setup`
source .venv/bin/activate
cvo --help
```

`setup.sh` does **everything**: creates the venv, runs `pip install -e .`,
creates `data/pdfs/`, `data/json/`, `output/`, copies `.env.example → .env`,
and finally launches the interactive `cvo setup` wizard so you can pick
your provider and paste your API key in one go. It's idempotent — safe to
re-run. Pass `SKIP_WIZARD=1` to skip the wizard step.

### Manual install

```bash
python3 -m venv .venv
source .venv/bin/activate            # Windows: .venv\Scripts\activate
pip install -e .                      # installs deps and the `cvo` command
cvo setup                             # interactive provider + key wizard
```

### Where to put your files

| Folder        | Purpose                                                        |
| ------------- | -------------------------------------------------------------- |
| `data/pdfs/`  | Drop your CV PDFs here (input). **Gitignored.**                |
| `data/json/`  | Parsed CV JSONs land here (input or processed). **Gitignored.**|
| `output/`     | Optimized CVs and reports. **Gitignored.**                     |

If you run `cvo run --offer offer.txt` without `--pdf` or `--cv`, the CLI
auto-detects CVs in `data/json/` and `data/pdfs/` and lets you pick.

## Usage

Three subcommands:

| Command           | Purpose                                                       |
| ----------------- | ------------------------------------------------------------- |
| `cvo setup`       | Pick provider + paste API key (saves to `.env`)               |
| `cvo run`         | Full pipeline: CV (PDF or JSON) + offer → optimized CV        |
| `cvo parse-pdf`   | Parse a CV PDF into the standard JSON (no alignment)          |

Run `cvo --help` or `cvo <command> --help` for the full flag list.

### `cvo setup` — interactive wizard

```bash
cvo setup                          # menu: pick 1-4, paste key, done
cvo setup --provider gemini        # skip the picker
cvo setup --force                  # re-prompt for the key
```

Writes `.env` with `CVO_PROVIDER=<choice>` plus the corresponding key.
The wizard hides the key as you type.

### `cvo run` — full pipeline

By default streams every LLM response to stdout phase by phase. Pass
`--quiet` for scripted runs.

```bash
# Auto-detect CV in data/  (will prompt if there are several)
cvo run --offer offer.txt

# From a PDF
cvo run --pdf data/pdfs/my_cv.pdf --offer offer.txt

# From a JSON (skip PDF parsing)
cvo run --cv examples/cv_example.json --offer examples/offer_example.txt

# Switch providers + ask for PDF + DOCX outputs
cvo run --offer offer.txt --provider gemini --format pdf,docx

# Quiet mode for CI / scripted runs
cvo run --cv my_cv.json --offer offer.txt --quiet
```

Useful flags:

- `--provider {claude,openai,gemini,deepseek}` — overrides the default
  (the one configured by `cvo setup`).
- `--model <name>` — override the default model for the active provider.
- `--pdf-provider <name>` — provider used for PDF→JSON parsing. Default:
  DeepSeek if you have its key, else the active provider.
- `--format <list>` — comma-separated formats. Options: `md`, `json`,
  `pdf`, `docx`, or `all`. Default: `md,json`.
- `--output <path>` — base output path (default `output/cv_optimized.md`).

### Output formats

Every run always produces the alignment report at
`output/cv_optimized_report.md` and writes the JSON + Markdown by default:

| Format | How it is built                                                          |
| ------ | ------------------------------------------------------------------------ |
| `md`   | ATS-friendly Markdown (no tables, no images, single column).             |
| `json` | Structured optimized CV — same shape as the input JSON, with metadata.   |
| `pdf`  | Built from the Markdown via **pandoc** (must be installed).              |
| `docx` | Built from the structured JSON via **python-docx** (no extra tools).     |

If `pandoc` isn't available, the PDF step is skipped with a warning and
the rest of the formats still get written. To install pandoc on macOS:

```bash
brew install pandoc
```

(Or see https://pandoc.org/installing.html.)

### `cvo parse-pdf` — PDF → JSON only

Just the PDF parsing step. Useful if you want to review/edit the JSON
before running the full alignment.

```bash
cvo parse-pdf --pdf my_cv.pdf
# → data/json/my_cv.json   (or alongside the PDF if data/json/ does not exist)

cvo parse-pdf --pdf my_cv.pdf --provider claude --model claude-sonnet-4-6
```

## How it works (architecture)

```
                ┌──────────────────────────────────────────┐
   PDF ──────►  │ Parser provider (CV_PARSER prompt)       │ ──► CV JSON
                └──────────────────────────────────────────┘
                                                                 │
                                                                 ▼
   Offer.txt ─► Active provider (ANALYZER prompt)    ──► offer analysis JSON
                                                                 │
                                                                 ▼
            ┌──────────── per experience ────────────┐
   CV ────► │ Active provider (ALIGNER) — strict     │ ──► aligned bullets + score
            └────────────────────────────────────────┘
                                                                 │
                                                                 ▼
   Active provider (SUMMARY)   ──► aligned professional summary
   Active provider (SKILLS)    ──► reordered skills + missing-skills list
                                                                 │
                                                                 ▼
   Local generators            ──► cv_optimized.{md,json,pdf,docx}
                                   cv_optimized_report.md
```

All prompts live in `cv_optimizer/prompts.py` — that's where ~90% of the
quality lives. Tweak prompts before changing code.

## Project layout

```
cv-optimizer/
├── setup.sh                          # one-shot bootstrap (./setup.sh --help)
├── pyproject.toml                    # package metadata + `cvo` entrypoint
├── requirements.txt                  # (kept for non-editable installs)
├── .gitignore
├── .env.example
├── data/
│   ├── pdfs/                         # your CV PDFs (gitignored)
│   └── json/                         # parsed CV JSONs (gitignored)
├── output/                           # optimized CVs + reports (gitignored)
├── examples/
│   ├── cv_example.json
│   └── offer_example.txt
└── cv_optimizer/
    ├── __init__.py
    ├── cli.py                        # ⭐ `cvo` command (run / parse-pdf / setup)
    ├── setup_wizard.py               # ⭐ interactive provider + key wizard
    ├── providers.py                  # ⭐ provider abstraction (4 providers)
    ├── exporters.py                  # ⭐ md/json/pdf/docx writers
    ├── client.py                     # Claude wrapper
    ├── openai_client.py              # ChatGPT wrapper
    ├── gemini_client.py              # Gemini wrapper
    ├── deepseek_client.py            # DeepSeek wrapper
    ├── models.py                     # CV / Experience dataclasses
    ├── prompts.py                    # ⭐ all prompts live here
    ├── analyzer.py                   # offer → structured analysis
    ├── aligner.py                    # per-experience alignment
    ├── summary.py                    # summary + skill reorder
    ├── generator.py                  # Markdown + structured JSON + report
    └── pdf_parser.py                 # PDF → text → JSON pipeline
```

## CV JSON schema

See `examples/cv_example.json`. Same shape applies to:
- the **input** JSON you feed `cvo run --cv …`
- the **output** JSON `cv_optimized.json` (with extra alignment metadata).

Minimum input shape:

```json
{
  "personal_info": {
    "name": "...",
    "current_title": "...",
    "email": "...",
    "phone": "...",
    "location": "...",
    "linkedin": "...",
    "github": "..."
  },
  "summary": "...",
  "experiences": [
    {
      "company": "...",
      "position": "...",
      "start_date": "...",
      "end_date": "...",
      "location": "...",
      "description": "...",
      "achievements": ["bullet 1", "bullet 2"],
      "technologies": ["..."]
    }
  ],
  "education": [
    {"degree": "...", "institution": "...", "period": "..."}
  ],
  "skills": {"category": ["skill1", "skill2"]},
  "certifications": [
    {"name": "...", "issuer": "...", "year": "..."}
  ],
  "languages": [
    {"language": "...", "level": "..."}
  ]
}
```

> 💡 **Tip:** in `achievements` put as much detail as you have, even if
> messy. The aligner works best with rich raw material — metrics, numbers,
> team sizes, scope, all of it. The model takes care of polishing.

## Iterating on quality

Quality lives in `cv_optimizer/prompts.py`. If a result isn't good enough:

1. Try a different provider: `cvo run … --provider claude --model claude-opus-4-7`.
2. Open `cv_optimizer/prompts.py` and tighten the rules. For instance, make
   `ALIGNER_SYSTEM` stricter about metrics, or change the bullet count.
3. To add a new step (e.g. an aligned "personal projects" section),
   follow the same pattern: prompt in `prompts.py` + module in
   `cv_optimizer/` + invocation in `cv_optimizer/cli.py`.

## Approximate cost

A 4-experience CV runs around:
- **Claude Sonnet:** $0.05–0.15 per run · **Opus:** $0.30–0.50.
- **GPT-4o:** $0.05–0.15 per run.
- **Gemini 2.0 Flash:** a few cents per run.
- **DeepSeek V4 Flash:** a few cents per run.

Plenty of room to iterate.

## Notes on languages

Prompts are written in English but explicitly instruct the model to
**preserve the original language of the source CV**. A Spanish CV will
stay Spanish; an English CV will stay English.
