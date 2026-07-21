# slidevault-export

**v0.1.0** — Export whole-slide images and annotations from [SlideVault](https://slidevault.hurondigitalpathology.com/) (Cytomine).

## Requirements

- Python 3.10+
- [`requests`](https://pypi.org/project/requests/)

```powershell
pip install -r requirements.txt
```

## Auth

Auth is **not** automatic. Log into SlideVault in your browser, then copy cookies into PowerShell env vars for the same window you use to run the script.

Do **not** paste cookies into the script or commit them to git.

1. Open SlideVault and sign in.
2. DevTools (F12) → **Application** → **Cookies**.
3. Copy cookie values:
   - `SESSION` (required)
   - `JSESSIONID` (optional)
   - `XSRF-TOKEN` (optional)
4. Set env vars:

```powershell
$env:SLIDEVAULT_SESSION = "paste SESSION value here"
$env:SLIDEVAULT_JSESSIONID = "paste JSESSIONID value here"
$env:SLIDEVAULT_XSRF_TOKEN = "paste XSRF-TOKEN value here"
```

## Finding project / image IDs

While logged in:

**Project id**

- DevTools → Network → Fetch/XHR → look for `project.json?max=0&offset=0`
- Or open:  
  `https://slidevault.hurondigitalpathology.com/core-service/api/project.json?max=0&offset=0`  
  Each item in `collection` has `id` and `name`.

**Image id**

- Open a project, then Network → `imageinstance.json?...`
- Or open:  
  `https://slidevault.hurondigitalpathology.com/core-service/api/project/<PROJECT_ID>/imageinstance.json?max=50&offset=0`  
  Each entry has `id` and `instanceFilename`.

## Usage

From the repo root, after setting env vars:

```powershell
# One image (recommended first test)
python slidevault_export.py --out ./exports --project-id 6430125 --image-id 6430571

# One project (all images)
python slidevault_export.py --out ./exports --project-id 6430125

# All projects
python slidevault_export.py --out ./exports
```

### Options

| Flag | Description |
|------|-------------|
| `--out` | Output directory (default: `slidevault_exports`) |
| `--project-id` | Export one project only |
| `--image-id` | Export one image only (requires `--project-id`) |

## Output

For each image, the script writes:

- The downloaded slide file (filename from the server when available)
- A matching `.xml` file with annotation fields (`id`, `location`, `area`, `perimeter`, `user`, `term`, etc.)

Layout:

```text
exports/
  <project_name>/
    slide.tif
    slide.xml
```
