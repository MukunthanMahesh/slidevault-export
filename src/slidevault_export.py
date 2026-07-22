"""
SlideVault (Cytomine) export: list projects/images, download slides + annotations.

Authentication: Playwright headless Keycloak login using SLIDEVAULT_USER and
SLIDEVAULT_PASSWORD. Server entrypoint: ./run_export.sh (see README).
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path
from xml.etree.ElementTree import Element, ElementTree, SubElement

import requests
from playwright.sync_api import sync_playwright

__version__ = "0.2.0"

HOST = "slidevault.hurondigitalpathology.com"
APP_URL = f"https://{HOST}/"
BASE = f"https://{HOST}/core-service"
API = f"{BASE}/api"

COOKIE_NAMES = ("SESSION", "JSESSIONID", "XSRF-TOKEN")

# ANSI colors for interactive terminals (disabled when stdout is not a TTY).
_USE_COLOR = sys.stdout.isatty()
_RESET = "\033[0m"
_CYAN = "\033[96m"      # project
_YELLOW = "\033[93m"    # download filename
_GREEN = "\033[92m"     # saved
_RED = "\033[91m"       # warnings
_MAGENTA = "\033[95m"   # skipped existing


def _c(color: str, text: str) -> str:
    if not _USE_COLOR:
        return text
    return f"{color}{text}{_RESET}"


def login_and_get_cookies() -> dict[str, str]:
    """Log in via Playwright (Keycloak) and return SlideVault cookies."""
    user = os.environ.get("SLIDEVAULT_USER")
    password = os.environ.get("SLIDEVAULT_PASSWORD")
    if not user or not password:
        sys.exit(
            "error: SLIDEVAULT_USER and SLIDEVAULT_PASSWORD must be set "
            "(see config/slidevault.env.example)."
        )

    print(f"[auth] credentials loaded (user={user})")
    print("[auth] launching headless Chromium")
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context()
        page = context.new_page()
        try:
            print(f"[auth] opening {APP_URL}")
            page.goto(APP_URL, wait_until="domcontentloaded")
            print(f"[auth] landed on {page.url}")

            print("[auth] waiting for Keycloak login form (#username)")
            page.wait_for_selector("#username", timeout=60_000)
            print("[auth] login form ready; filling username and password")
            page.fill("#username", user)
            page.fill("#password", password)

            print("[auth] submitting login (#kc-login)")
            page.click("#kc-login")

            print(f"[auth] waiting for redirect back to https://{HOST}/...")
            page.wait_for_url(re.compile(rf"https://{re.escape(HOST)}/.*"), timeout=60_000)
            print(f"[auth] redirect complete: {page.url}")

            print("[auth] waiting for SESSION cookie")
            cookies: dict[str, str] = {}
            for attempt in range(120):  # up to ~60s
                cookies = {
                    c["name"]: c["value"]
                    for c in context.cookies()
                    if c["name"] in COOKIE_NAMES
                }
                if "SESSION" in cookies:
                    print(f"[auth] SESSION cookie found after {attempt * 500}ms")
                    break
                if attempt % 10 == 0:
                    present = ", ".join(sorted(cookies)) or "(none)"
                    print(f"[auth] polling cookies ({attempt * 500}ms): {present}")
                page.wait_for_timeout(500)

            if "SESSION" not in cookies:
                present = ", ".join(
                    sorted({c["name"] for c in context.cookies()})
                ) or "(none)"
                print(f"[auth] cookies present at failure: {present}", file=sys.stderr)
                sys.exit(
                    "error: login completed without a SESSION cookie "
                    "(credentials or Keycloak form selectors may be wrong)."
                )

            found = ", ".join(sorted(cookies))
            print(f"[auth] login ok; exporting cookies: {found}")
            return cookies
        finally:
            print("[auth] closing browser")
            browser.close()


def session_from_playwright() -> requests.Session:
    cookies = login_and_get_cookies()
    sess = requests.Session()
    sess.cookies.set("SESSION", cookies["SESSION"], domain=HOST)
    if "JSESSIONID" in cookies:
        sess.cookies.set("JSESSIONID", cookies["JSESSIONID"], domain=HOST)
    if "XSRF-TOKEN" in cookies:
        sess.cookies.set("XSRF-TOKEN", cookies["XSRF-TOKEN"], domain=HOST)
        sess.headers["X-XSRF-TOKEN"] = cookies["XSRF-TOKEN"]
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


def _fmt_bytes(n: int) -> str:
    size = float(n)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024 or unit == "TB":
            if unit == "B":
                return f"{int(size)} {unit}"
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"


def download_image(s: requests.Session, image_id: int, dest: Path) -> Path:
    r = s.get(f"{API}/imageinstance/{image_id}/download", stream=True)
    r.raise_for_status()
    cd = r.headers.get("Content-Disposition", "")
    match = re.search(r'filename="?([^";]+)"?', cd)
    if match:
        dest = dest.with_name(match.group(1))

    total = int(r.headers.get("Content-Length") or 0)
    done = 0
    last_print = 0
    tty = sys.stdout.isatty()

    with dest.open("wb") as f:
        for chunk in r.iter_content(chunk_size=1024 * 1024):
            if not chunk:
                continue
            f.write(chunk)
            done += len(chunk)

            if not tty and done - last_print < 8 * 1024 * 1024 and done != total:
                continue
            last_print = done

            if total > 0:
                pct = 100.0 * done / total
                line = f"    progress {_fmt_bytes(done)} / {_fmt_bytes(total)} ({pct:5.1f}%)"
            else:
                line = f"    progress {_fmt_bytes(done)}"
            if tty:
                print(f"\r{line}", end="", flush=True)
            else:
                print(line, flush=True)

    if tty and done:
        print()
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
    force: bool = False,
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
    print(_c(_CYAN, f"Project {project_name} ({project_id}): {len(images)} image(s)"))

    for img in images:
        image_id = img["id"]
        filename = img.get("instanceFilename") or img.get("filename") or f"{image_id}.tif"
        stem = safe_stem(filename)
        image_path = project_dir / filename
        xml_path = project_dir / f"{stem}.xml"

        if not force and image_path.is_file() and image_path.stat().st_size > 0:
            print(_c(_MAGENTA, f"  skip {filename} (already exists)"))
            continue

        print(f"  downloading {_c(_YELLOW, filename)} ...")
        try:
            download_image(s, image_id, image_path)
        except requests.HTTPError as e:
            print(_c(_RED, f"  WARN download failed for {image_id}: {e}"))
            continue

        anns = fetch_annotations(s, image_id)
        tree = ElementTree(annotations_to_xml(anns, filename))
        tree.write(xml_path, encoding="utf-8", xml_declaration=True)
        print(_c(_GREEN, f"  saved {xml_path.name} ({len(anns)} annotations)"))


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Export SlideVault images + annotations (requires SLIDEVAULT_USER/PASSWORD)"
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
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-download and overwrite existing slide files",
    )
    args = parser.parse_args()

    if args.image_id is not None and args.project_id is None:
        sys.exit("--image-id requires --project-id")

    print("Logging in via Playwright...")
    s = session_from_playwright()
    print("-" * 60)
    args.out.mkdir(parents=True, exist_ok=True)

    projects = list_projects(s)
    if args.project_id is not None:
        projects = [p for p in projects if p["id"] == args.project_id]
        if not projects:
            sys.exit(f"Project {args.project_id} not found or not visible")

    for project in projects:
        export_project(
            s, project, args.out, image_id=args.image_id, force=args.force
        )

    print("Done.")


if __name__ == "__main__":
    main()
