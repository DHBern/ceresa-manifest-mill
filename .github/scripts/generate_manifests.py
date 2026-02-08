#!/usr/bin/env python3
"""
generate_manifests.py

Reads manifest file, groups by document, generates IIIF presentation manifests.

Usage:
  python generate_manifests.py \
    --input-file input/all-manifests.txt \
    --output-dir _generated/presentation \
    --report-file _generated/manifest-generation-report.md \
    --iiif-image-base "https://iiif.ub.unibe.ch/image/v3/" \
    --project-segment "ceresa" \
    --iiif-presentation-base "https://iiif.arcipelago-ceresa.digitaleditions.ch"
"""

import argparse
import os
import re
import sys
import json
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed
from collections import defaultdict
from IIIFpres import iiifpapi3

REQUEST_TIMEOUT = 10
MAX_WORKERS = 8

def parse_all_manifests(path):
    """Parse manifest file and return list of paths."""
    paths = []
    line_re = re.compile(r'^\s*([0-9a-fA-F]+)\s+(.+?)\s*$')
    with open(path, 'r', encoding='utf-8') as fh:
        for ln in fh:
            ln = ln.rstrip('\n')
            if not ln.strip():
                continue
            m = line_re.match(ln)
            if m:
                paths.append(m.group(2))
            else:
                # If line doesn't match checksum format, try using whole line
                paths.append(ln.strip())
    return paths

def doc_and_filename_from_path(p):
    parts = p.strip().split('/')
    if len(parts) == 1:
        return ("root", parts[-1])
    elif len(parts) >= 2:
        return (parts[-2], parts[-1])
    else:
        return ("root", p)

def build_service_id(iiif_base, project_segment, path):
    """
    Build IIIF Image service id as:
      <iiif_base>/<project_segment>/<filename>
    If path is already a URL, use as-is.
    """
    path = path.strip()
    if path.startswith('http://') or path.startswith('https://'):
        return path.rstrip('/').replace('/info.json', '')
    if not iiif_base:
        raise ValueError(f"No IIIF_IMAGE_BASE provided and path is not a URL: {path}")
    filename = os.path.basename(path)
    iiif_base = iiif_base.rstrip('/')
    project_segment = project_segment.strip('/')
    if project_segment:
        service = f"{iiif_base}/{project_segment}/{filename}"
    else:
        service = f"{iiif_base}/{filename}"
    return service.rstrip('/')

def fetch_info_json(service_id, session):
    info_url = service_id.rstrip('/') + '/info.json'
    try:
        r = session.get(info_url, timeout=REQUEST_TIMEOUT)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        status = getattr(e, 'response', None) and e.response.status_code or None
        return {'error': str(e), 'status_code': status, 'info_url': info_url}

def safe_int(v, default=0):
    try:
        return int(v)
    except Exception:
        return default

def make_manifest_for_doc(doc, items, iiif_image_base, project_segment, iiif_presentation_base, session):
    """
    items: list of original path strings
    Returns (manifest_json_str, created_count, failures_list)
    """
    failures = []
    canvases_created = 0
    
    # Sort items to ensure proper sequential order (001, 002, 003, 004...)
    items = sorted(items)

    # Ensure BASE_URL ends with / for pyIIIFpres
    if iiif_presentation_base:
        iiifpapi3.BASE_URL = iiif_presentation_base.rstrip('/') + '/'
    else:
        iiifpapi3.BASE_URL = "https://example.org/iiif/"

    manifest = iiifpapi3.Manifest()
    manifest_id = f"{doc}.json"
    manifest.set_id(extendbase_url=manifest_id)
    manifest.add_label("en", doc)
    manifest.add_behavior("paged")

    # Fetch all info.json files in parallel but preserve order
    jobs = {}
    with ThreadPoolExecutor(max_workers=min(MAX_WORKERS, max(2, len(items)))) as ex:
        for p in items:
            try:
                service_id = build_service_id(iiif_image_base, project_segment, p)
            except Exception as e:
                failures.append((p, f"service id build failed: {e}"))
                continue
            jobs[ex.submit(fetch_info_json, service_id, session)] = (p, service_id)

        # Collect results in a dict keyed by path to preserve order
        results = {}
        for fut in as_completed(jobs):
            p, service_id = jobs[fut]
            info = fut.result()
            results[p] = (info, service_id)
    
    # Now process results in the original sorted order
    for p in items:
        if p not in results:
            continue  # Was skipped due to service_id build failure
        
        info, service_id = results[p]
        
        if isinstance(info, dict) and info.get('error'):
            failures.append((p, f"info.json fetch failed for {info.get('info_url', service_id+'/info.json')}: {info.get('error')}"))
            continue

        width = safe_int(info.get('width', 0), 0)
        height = safe_int(info.get('height', 0), 0)

        try:
            canvases_created += 1
            canvas = manifest.add_canvas_to_items()
            canvas.set_id(extendbase_url=f"canvas/p{canvases_created}")
            canvas.set_width(width)
            canvas.set_height(height)
            canvas.add_label("en", os.path.basename(p))

            annopage = canvas.add_annotationpage_to_items()
            annopage.set_id(extendbase_url=f"page/p{canvases_created}/1")
            annotation = annopage.add_annotation_to_items(target=canvas.id)
            annotation.set_id(extendbase_url=f"annotation/p{str(canvases_created).zfill(4)}-image")
            annotation.set_motivation("painting")

            body_id = service_id
            annotation.body.set_id(body_id)
            annotation.body.set_type("Image")

            fmt = None
            if 'formats' in info and isinstance(info['formats'], list) and info['formats']:
                fmt = 'image/jpeg'
            if not fmt:
                if p.lower().endswith(('.tif', '.tiff')):
                    fmt = 'image/tiff'
                else:
                    fmt = 'image/jpeg'
            annotation.body.set_format(fmt)
            annotation.body.set_width(width)
            annotation.body.set_height(height)

            s = annotation.body.add_service()
            s.set_id(service_id)
            s.set_type("ImageService3")
            profile = "level1"
            if isinstance(info.get('profile'), str):
                profile = info.get('profile')
            elif isinstance(info.get('profile'), list) and info.get('profile'):
                profile = info['profile'][0]
            s.set_profile(profile)

        except Exception as e:
            failures.append((p, f"manifest/canvas creation error: {e}"))
            canvases_created -= 1  # Decrement since we failed to create this canvas
            continue

    try:
        manifest_json = manifest.json_dumps()
        return manifest_json, canvases_created, failures
    except Exception as e:
        return None, canvases_created, failures + [("manifest_dumps", f"json_dumps failed: {e}")]

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input-file", required=True)
    ap.add_argument("--output-dir", required=True)
    ap.add_argument("--report-file", required=True)
    ap.add_argument("--iiif-image-base", default="")
    ap.add_argument("--project-segment", default="")
    ap.add_argument("--iiif-presentation-base", default="")
    args = ap.parse_args()

    if not os.path.exists(args.input_file):
        print(f"Input file {args.input_file} not found", file=sys.stderr)
        sys.exit(2)

    paths = parse_all_manifests(args.input_file)
    print(f"Parsed {len(paths)} paths from {args.input_file}")

    grouped = defaultdict(list)
    for p in paths:
        doc, fname = doc_and_filename_from_path(p)
        grouped[doc].append(p)

    print(f"Grouped into {len(grouped)} documents")

    os.makedirs(args.output_dir, exist_ok=True)
    report_lines = []
    created_manifests = []
    total_failures = []

    with requests.Session() as session:
        session.headers.update({'User-Agent': 'generate_manifests/1.0'})
        for doc, items in sorted(grouped.items()):
            print(f"Processing document {doc} ({len(items)} images)...")
            manifest_json, created_count, failures = make_manifest_for_doc(
                doc=doc,
                items=items,
                iiif_image_base=args.iiif_image_base,
                project_segment=args.project_segment,
                iiif_presentation_base=args.iiif_presentation_base,
                session=session
            )
            if manifest_json:
                out_path = os.path.join(args.output_dir, f"{doc}.json")
                with open(out_path, 'w', encoding='utf-8') as fh:
                    fh.write(manifest_json)
                created_manifests.append((doc, out_path, created_count))
                report_lines.append(f"- {doc}: created {created_count} canvases -> {out_path}")
            else:
                report_lines.append(f"- {doc}: FAILED to create manifest (no json produced)")
            if failures:
                total_failures.extend([(doc, p, msg) for (p, msg) in failures])

    with open(args.report_file, 'w', encoding='utf-8') as rf:
        rf.write("# IIIF Manifest Generation Report\n\n")
        rf.write(f"Input file: {args.input_file}\n\n")
        rf.write("## Created manifests\n\n")
        if created_manifests:
            for doc, path, cnt in created_manifests:
                rf.write(f"- **{doc}**: {cnt} canvases — `{path}`\n")
        else:
            rf.write("No manifests were created.\n")
        rf.write("\n## Failures\n\n")
        if total_failures:
            for doc, p, msg in total_failures:
                rf.write(f"- document `{doc}`, item `{p}`: {msg}\n")
        else:
            rf.write("✅ No per-image failures recorded.\n")

    print("=== SUMMARY ===")
    print(f"Manifests created: {len(created_manifests)}")
    print(f"Total failures (per-image): {len(total_failures)}")
    print(f"Report: {args.report_file}")

if __name__ == "__main__":
    main()
