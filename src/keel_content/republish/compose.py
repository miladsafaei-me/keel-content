"""Turn a plan into shippable artifacts: bundles, drawn figures, graft payloads.

Figures are drawn by ``page_extract`` builders from the parameters the plan
carries, so a figure is generated rather than copied, and it comes out in the
host's brand with the host's watermark.
"""
from __future__ import annotations

import json
from pathlib import Path

from .plan import validate_plan


def _brand(brand_path=None, logo_path=None):
    from page_extract import Brand
    if brand_path:
        return Brand.load(brand_path)
    if logo_path:
        return Brand.from_logo(logo_path)
    return Brand()


def draw_figure(spec, brand, out_dir, stem) -> dict:
    """Draw one figure and rasterize it. Returns the bundle-shaped record."""
    from page_extract.figures import build
    from page_extract.raster import svg_to_webp

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    svg_path = out_dir / f"{spec['id']}.svg"
    svg_path.write_text(build(spec["builder"], brand, spec.get("params") or {}),
                        encoding="utf-8")
    webp_path = out_dir / f"{spec['id']}.webp"
    _, (w, h) = svg_to_webp(svg_path, webp_path, spec.get("width", 1200))
    return {
        "id": spec["id"],
        "file": f"{stem}.figures/{spec['id']}.webp",
        "svg": f"{stem}.figures/{spec['id']}.svg",
        "width": w, "height": h,
        "alt": spec["alt"], "caption": spec["caption"],
        "comprehension_job": spec.get("comprehension_job", spec["caption"]),
        "section": spec.get("section", "Introduction"),
    }


def compose_post(output, out_dir, brand) -> Path:
    out_dir = Path(out_dir)
    slug = output["slug"]
    bundle = dict(output["bundle"])
    figures = [draw_figure(f | {"id": f["id"]}, brand,
                           out_dir / f"{slug}.figures", slug)
               for f in (output.get("figures") or [])]
    bundle.update({
        "content_id": slug,
        "slug": slug,
        "target": bundle.get("target", "blog"),
        "h1": bundle.get("h1", bundle["title"]),
        "initial_status": bundle.get("initial_status", "draft"),
        "featured_image_url": bundle.get("featured_image_url", ""),
        "video_embeds": bundle.get("video_embeds", []),
        "asset_requests": bundle.get("asset_requests", []),
        "author_slug": bundle.get("author_slug"),
        "reviewer_slug": bundle.get("reviewer_slug"),
        "figures": figures,
        "figure_requests": [
            {"id": f["id"], "section": f["section"],
             "comprehension_job": f["comprehension_job"],
             "content_notes": f["comprehension_job"],
             "takeaway": f["caption"], "caption": f["caption"], "alt": f["alt"]}
            for f in figures
        ],
    })
    path = out_dir / f"{slug}.bundle.json"
    path.write_text(json.dumps(bundle, ensure_ascii=False, indent=1), encoding="utf-8")
    return path


def compose_graft(output, out_dir, brand, index) -> Path:
    out_dir = Path(out_dir)
    gid = output.get("graft_id") or f"{output['target_slug']}-{index}"
    payload = {"graft_id": gid, "target_slug": output["target_slug"],
               "anchor": output["anchor"], "source": output.get("from")}
    if output.get("visual"):
        payload["visual"] = output["visual"]
    else:
        # A grafted figure is drawn here and referenced by absolute path, because
        # the graft command runs where the media root is, not where this ran.
        spec = dict(output["figure"])
        spec.setdefault("id", gid)
        fig_dir = out_dir / f"{gid}.figures"
        rec = draw_figure(spec, brand, fig_dir, gid)
        rec["file"] = str(fig_dir / f"{spec['id']}.webp")
        rec["svg"] = str(fig_dir / f"{spec['id']}.svg")
        payload["figure"] = rec
    path = out_dir / f"graft-{gid}.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    return path


def compose(workspace, brand_path=None, logo_path=None) -> dict:
    """Read ``<workspace>/plan.json`` and write everything it describes."""
    ws = Path(workspace)
    plan = json.loads((ws / "plan.json").read_text(encoding="utf-8"))
    problems = validate_plan(plan)
    if problems:
        raise ValueError("plan.json is not valid:\n  - " + "\n  - ".join(problems))

    brand = _brand(brand_path, logo_path)
    out_dir = ws / "out"
    out_dir.mkdir(exist_ok=True)
    written = {"posts": [], "grafts": []}
    for i, output in enumerate(plan["outputs"]):
        if output["kind"] == "post":
            written["posts"].append(str(compose_post(output, out_dir, brand)))
        else:
            written["grafts"].append(str(compose_graft(output, out_dir, brand, i)))
    (ws / "composed.json").write_text(json.dumps(written, indent=1), encoding="utf-8")
    return written
