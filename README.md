# slidevault-export

**v0.2.0** — Export whole-slide images and annotations from [SlideVault](https://slidevault.hurondigitalpathology.com/) (Cytomine).

This program is intended for compute-server execution so assets land on project-specific storage. Authentication uses Playwright (headless Chromium) against Keycloak SSO. Credentials must not be committed.

## Layout

```text
vault-pull/
  run_export.sh                 # server entrypoint
  requirements.txt
  config/
    slidevault.env.example      # template -> slidevault.env (gitignored)
  src/
    slidevault_export.py        # exporter
  exports/                      # default output when SLIDEVAULT_OUT is unset
```

## Server setup

### 1. Install

```bash
git clone <repo-url> vault-pull
cd vault-pull

python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium
# Linux shared-library dependencies (if Chromium fails to launch):
# playwright install-deps
```

### 2. Configure credentials

```bash
cp config/slidevault.env.example slidevault.env
chmod 600 slidevault.env
```

Required variables in `slidevault.env`:

| Variable              | Description                                                                       |
| --------------------- | --------------------------------------------------------------------------------- |
| `SLIDEVAULT_USER`     | SlideVault / Keycloak username                                                    |
| `SLIDEVAULT_PASSWORD` | SlideVault / Keycloak password                                                    |
| `SLIDEVAULT_OUT`      | Absolute output directory for slides and XML (optional; default `<repo>/exports`) |

Only `config/slidevault.env.example` is tracked. `slidevault.env` is gitignored.

### 3. Run

```bash
chmod +x run_export.sh

# One project
./run_export.sh --project-id 6430125

# One image
./run_export.sh --project-id 6430125 --image-id 6430571

# All visible projects
./run_export.sh
```

`run_export.sh` activates `.venv`, sources `slidevault.env`, and invokes `src/slidevault_export.py`. Additional CLI flags are forwarded. For overnight jobs, invoke `./run_export.sh` from the site scheduler (cron, systemd, Slurm, or equivalent).

### CLI options

| Flag           | Description                                                               |
| -------------- | ------------------------------------------------------------------------- |
| `--out`        | Output directory (set automatically from `SLIDEVAULT_OUT` by the wrapper) |
| `--project-id` | Limit export to one project                                               |
| `--image-id`   | Limit export to one image (requires `--project-id`)                       |
| `--force`      | Re-download and overwrite existing slide files                            |

By default, images whose slide file already exists on disk (non-empty) are **skipped** so overnight jobs can resume safely. Use `--force` to replace them.

### Output layout

```text
$SLIDEVAULT_OUT/
  <project_name>/
    slide.tif
    slide.xml
```

Each image is written with a sibling `.xml` file containing annotation fields (`id`, `location`, `area`, `perimeter`, `user`, `term`, etc.).

## Project and image IDs

While authenticated in the SlideVault UI:

**Project id** — DevTools Network -> `project.json?max=0&offset=0`, or:  
`https://slidevault.hurondigitalpathology.com/core-service/api/project.json?max=0&offset=0`  
Items in `collection` include `id` and `name`.

**Image id** — Network -> `imageinstance.json`, or:  
`https://slidevault.hurondigitalpathology.com/core-service/api/project/<PROJECT_ID>/imageinstance.json?max=50&offset=0`  
Entries include `id` and `instanceFilename`.

## Local development (optional)

For a single-image smoke test on Windows:

```powershell
cd path\to\vault-pull
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
playwright install chromium

$env:SLIDEVAULT_USER = "..."
$env:SLIDEVAULT_PASSWORD = "..."
python src\slidevault_export.py --out .\exports --project-id 6430125 --image-id 6430571
```

Full project exports should run on the compute server. On Windows, call `src\slidevault_export.py` directly; `run_export.sh` targets Linux.
