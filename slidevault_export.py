"""
SlideVault (Cytomine) export: list projects/images, download slides + annotations.

Auth is NOT automatic. Keycloak SSO sets cookies in the browser; copy them into
PowerShell env vars before running. Do NOT paste cookies into this file or commit
them to git. Env vars only last for that PowerShell window.


------------------------------------------------------------------------
1) SET AUTH (Windows PowerShell)
------------------------------------------------------------------------
1. Log into SlideVault in your browser. (https://slidevault.hurondigitalpathology.com/)

2. Open DevTools (F12) → Application → Cookies

3. Copy cookie Values:
   - SESSION          (required)
   - JSESSIONID       (optional)
   - XSRF-TOKEN       (optional)

4. Register the env vars in the same PowerShell window you will use to run the script:

     $env:SLIDEVAULT_SESSION = "paste SESSION value here"
     $env:SLIDEVAULT_JSESSIONID = "paste JSESSIONID value here"
     $env:SLIDEVAULT_XSRF_TOKEN = "paste XSRF-TOKEN value here"


------------------------------------------------------------------------
2) HOW TO GET PROJECT / IMAGE IDS
------------------------------------------------------------------------
While logged in (browser still has your session):

  Project id
    - DevTools → Network → Fetch/XHR → look for:
        project.json?max=0&offset=0
    - Open that request → Response: each item in "collection" has "id" and "name"
    - Or open in the address bar (JSON):
        https://slidevault.hurondigitalpathology.com/core-service/api/project.json?max=0&offset=0
      → use the "id" for the project you want
    - You may also see the id in other URLs after opening a project, e.g.:
        .../api/project/6430125/imageinstance.json
      → project id is 6430125

  Image id
    - Open the project, then Network → imageinstance.json?max=50&...
    - In the JSON response, each entry in "collection" has:
        "id": 6430571,
        "instanceFilename": "TVA74.tif"
    - Or open in the address bar (JSON):
        https://slidevault.hurondigitalpathology.com/core-service/api/project/6430125/imageinstance.json?max=50&offset=0
      → pick the "id" for the file you want


------------------------------------------------------------------------
3) USAGE
------------------------------------------------------------------------
From the repo root, after setting env vars above:

  One image (recommended first test):

     python temp/slidevault_export.py --out ./exports --project-id 6430125 --image-id 6430571

  One project (all images):

     python temp/slidevault_export.py --out ./exports --project-id 6430125

  All projects:

     python temp/slidevault_export.py --out ./exports
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path
from xml.etree.ElementTree import Element, ElementTree, SubElement

import requests

__version__ = "0.1.0"

BASE = "https://slidevault.hurondigitalpathology.com/core-service"
API = f"{BASE}/api"


def session_from_env() -> requests.Session:
    sess = requests.Session()
    cookie = os.environ.get("SLIDEVAULT_SESSION")
    if not cookie:
        sys.exit(
            "SLIDEVAULT_SESSION is not set.\n"
            "Copy SESSION from DevTools → Application → Cookies, then in PowerShell run:\n"
            '  $env:SLIDEVAULT_SESSION = "paste the SESSION value here"'
        )
    sess.cookies.set("SESSION", cookie, domain="slidevault.hurondigitalpathology.com")
    if os.environ.get("SLIDEVAULT_JSESSIONID"):
        sess.cookies.set(
            "JSESSIONID",
            os.environ["SLIDEVAULT_JSESSIONID"],
            domain="slidevault.hurondigitalpathology.com",
        )
    if os.environ.get("SLIDEVAULT_XSRF_TOKEN"):
        token = os.environ["SLIDEVAULT_XSRF_TOKEN"]
        sess.cookies.set("XSRF-TOKEN", token, domain="slidevault.hurondigitalpathology.com")
        sess.headers["X-XSRF-TOKEN"] = token
    sess.headers["Accept"] = "application/json"
    return sess


def list_projects(s: requests.Session) -> list[dict]:
    r = s.get(f"{API}/project.json", params={"max": 0, "offset": 0})
    r.raise_for_status()
    data = r.json()
    return data.get("collection", data if isinstance(data, list) else [])


def list_images(s: requests.Session, project_id: int, page_size: int = 50) -> list[dict]:
    images: list[dict] = []
    offset = 0
    while True:
        r = s.get(
            f"{API}/project/{project_id}/imageinstance.json",
            params={"max": page_size, "offset": offset, "order": "asc"},
        )
        r.raise_for_status()
        data = r.json()
        batch = data.get("collection", [])
        images.extend(batch)
        total = data.get("size", len(images))
        offset += page_size
        if offset >= total or not batch:
            break
    return images


def get_image(s: requests.Session, image_id: int) -> dict:
    r = s.get(f"{API}/imageinstance/{image_id}.json")
    r.raise_for_status()
    return r.json()


def download_image(s: requests.Session, image_id: int, dest: Path) -> Path:
    r = s.get(f"{API}/imageinstance/{image_id}/download", stream=True)
    r.raise_for_status()
    cd = r.headers.get("Content-Disposition", "")
    match = re.search(r'filename="?([^";]+)"?', cd)
    if match:
        dest = dest.with_name(match.group(1))
    with dest.open("wb") as f:
        for chunk in r.iter_content(chunk_size=1024 * 1024):
            if chunk:
                f.write(chunk)
    return dest


def fetch_annotations(s: requests.Session, image_id: int) -> list[dict]:
    r = s.get(f"{API}/annotation.json", params={"image": image_id})
    r.raise_for_status()
    data = r.json()
    return data.get("collection", data if isinstance(data, list) else [])


def annotations_to_xml(annotations: list[dict], image_name: str) -> Element:
    """Minimal XML wrapper around Cytomine annotation JSON fields."""
    root = Element("annotations", {"image": image_name})
    for ann in annotations:
        el = SubElement(root, "annotation")
        for key in ("id", "location", "area", "perimeter", "user", "image", "project"):
            if key in ann and ann[key] is not None:
                el.set(key, str(ann[key]))
        if "term" in ann and ann["term"] is not None:
            el.set("term", str(ann["term"]))
    return root


def safe_stem(name: str) -> str:
    return Path(name).stem or "image"


def export_project(
    s: requests.Session,
    project: dict,
    out_dir: Path,
    image_id: int | None = None,
) -> None:
    project_id = project["id"]
    project_name = project.get("name") or str(project_id)
    project_dir = out_dir / re.sub(r'[<>:"/\\|?*]', "_", project_name)
    project_dir.mkdir(parents=True, exist_ok=True)

    if image_id is not None:
        img = get_image(s, image_id)
        proj = img.get("project")
        if proj is not None and proj != project_id:
            sys.exit(f"Image {image_id} is not in project {project_id}")
        images = [img]
    else:
        images = list_images(s, project_id)
    print(f"Project {project_name} ({project_id}): {len(images)} image(s)")

    for img in images:
        image_id = img["id"]
        filename = img.get("instanceFilename") or img.get("filename") or f"{image_id}.tif"
        stem = safe_stem(filename)
        image_path = project_dir / filename
        xml_path = project_dir / f"{stem}.xml"

        print(f"  downloading {filename} ...")
        try:
            download_image(s, image_id, image_path)
        except requests.HTTPError as e:
            print(f"  WARN download failed for {image_id}: {e}")
            continue

        anns = fetch_annotations(s, image_id)
        tree = ElementTree(annotations_to_xml(anns, filename))
        tree.write(xml_path, encoding="utf-8", xml_declaration=True)
        print(f"  saved {xml_path.name} ({len(anns)} annotations)")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Export SlideVault images + annotations (requires SLIDEVAULT_SESSION)"
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument("--out", type=Path, default=Path("slidevault_exports"))
    parser.add_argument("--project-id", type=int, default=None, help="Export one project only")
    parser.add_argument(
        "--image-id",
        type=int,
        default=None,
        help="Export one image only (use with --project-id)",
    )
    args = parser.parse_args()

    if args.image_id is not None and args.project_id is None:
        sys.exit("--image-id requires --project-id")

    s = session_from_env()
    args.out.mkdir(parents=True, exist_ok=True)

    projects = list_projects(s)
    if args.project_id is not None:
        projects = [p for p in projects if p["id"] == args.project_id]
        if not projects:
            sys.exit(f"Project {args.project_id} not found or not visible")

    for project in projects:
        export_project(s, project, args.out, image_id=args.image_id)

    print("Done.")


if __name__ == "__main__":
    main()