#!/usr/bin/env python3
"""
zenodo_deposit.py
Build the archive bundle and upload it to Zenodo as a DRAFT deposition.

Deliberately does NOT publish. A published Zenodo record cannot be deleted (only superseded by
a new version), so the last step stays a human decision: this script uploads the bundle and
prints the draft's URL for you to review and publish in the browser. Pass --publish only if you
want to skip that review.

The API token is read from the ZENODO_API_TOKEN environment variable and is never written to
disk, echoed, or included in the bundle. Practise on the sandbox first (--sandbox), which is a
separate site with its own account, its own token, and throwaway DOIs.

Typical use, from the repo root:
    $env:ZENODO_API_TOKEN = "..."                      # PowerShell
    python scripts/zenodo_deposit.py --sandbox         # rehearse
    python scripts/zenodo_deposit.py                   # real draft, then publish in the browser
"""
import argparse
import json
import os
import subprocess
from pathlib import Path

import requests

LIVE = "https://zenodo.org/api"
SANDBOX = "https://sandbox.zenodo.org/api"


# Paths excluded from the archive for licensing reasons. The replay plans are derived from the
# StatsBomb open dataset, which is CC BY-NC 4.0; a derivative of NC-licensed data cannot be
# redistributed inside an MIT-licensed record. They are regenerable byte-for-byte from the
# pinned upstream commit with scripts/make_replay_plan.py, so excluding them costs nothing in
# reproducibility and keeps the record's licence honest.
NC_DERIVED_PATHS = ("data/processed/replay_plans",)


def build_bundle(out_zip, ref="HEAD", prefix="streaming-latency-sports/",
                 exclude=NC_DERIVED_PATHS, paths=(".",)):
    """Archive the tracked tree at `ref` with git, so gitignored data is excluded by design.

    `exclude` additionally drops paths that must not appear in the record. git pathspec magic
    (":(exclude)") is used rather than post-processing the zip, so the exclusion is applied by
    git itself and cannot be silently defeated by a later file being added under that path.
    """
    out = Path(out_zip)
    out.parent.mkdir(parents=True, exist_ok=True)
    pathspecs = list(paths) + [f":(exclude){p}" for p in exclude]
    subprocess.run(
        ["git", "archive", "--format=zip", f"--prefix={prefix}", "-o", str(out), ref,
         "--", *pathspecs],
        check=True, capture_output=True,
    )
    return out


def load_metadata(path=".zenodo.json"):
    """Read .zenodo.json and wrap it the way the deposition API expects."""
    meta = json.loads(Path(path).read_text(encoding="utf-8"))
    return {"metadata": meta}


def create_deposition(api, token, metadata, session=None):
    s = session or requests
    r = s.post(f"{api}/deposit/depositions", params={"access_token": token}, json=metadata)
    r.raise_for_status()
    return r.json()


def new_version(api, token, record_id, session=None):
    """Open a new-version draft of an existing published record.

    A new version keeps the record's **concept DOI** --- the one that always resolves to the
    latest version, `10.5281/zenodo.21650031` for the code record and `...21650064` for the
    dataset --- and mints a fresh version DOI beside it. That is what makes "the DOI stays the
    same" true: cite the concept DOI and every future version is reachable from it.

    Creating a fresh deposition instead, which is all this script could do until now, would
    have minted a *new concept DOI* and orphaned the citation chain.

    Zenodo hands back the parent record with a `latest_draft` link rather than the draft
    itself, so the draft is fetched in a second call.
    """
    s = session or requests
    r = s.post(f"{api}/deposit/depositions/{record_id}/actions/newversion",
               params={"access_token": token})
    r.raise_for_status()
    draft_url = r.json()["links"]["latest_draft"]
    d = s.get(draft_url, params={"access_token": token})
    d.raise_for_status()
    return d.json()


def clear_files(api, token, deposition, session=None):
    """Remove the files a new-version draft inherits from the version before it.

    Zenodo copies the previous version's files into the draft. Uploading this release's bundle
    without clearing them first leaves a record carrying two zips and two manifests, one pair
    of them stale, which is precisely the sort of thing this project's manifests exist to stop.
    """
    s = session or requests
    removed = []
    for f in deposition.get("files", []):
        r = s.delete(f"{api}/deposit/depositions/{deposition['id']}/files/{f['id']}",
                     params={"access_token": token})
        r.raise_for_status()
        removed.append(f.get("filename", f["id"]))
    return removed


def update_metadata(api, token, deposition_id, metadata, session=None):
    """Write this release's metadata over what the draft inherited."""
    s = session or requests
    r = s.put(f"{api}/deposit/depositions/{deposition_id}",
              params={"access_token": token}, json=metadata)
    r.raise_for_status()
    return r.json()


def upload_file(api, token, deposition, path, session=None):
    """Upload via the bucket API (handles large files better than the legacy files endpoint)."""
    s = session or requests
    bucket = deposition["links"]["bucket"]
    with open(path, "rb") as fh:
        r = s.put(f"{bucket}/{Path(path).name}", data=fh, params={"access_token": token})
    r.raise_for_status()
    return r.json()


def publish(api, token, deposition_id, session=None):
    s = session or requests
    r = s.post(f"{api}/deposit/depositions/{deposition_id}/actions/publish",
               params={"access_token": token})
    r.raise_for_status()
    return r.json()


def main(argv=None):
    ap = argparse.ArgumentParser(description="Upload the release bundle to Zenodo as a draft")
    ap.add_argument("--sandbox", action="store_true", help="use sandbox.zenodo.org (throwaway DOIs)")
    ap.add_argument("--ref", default="HEAD", help="git ref to archive (e.g. a release tag)")
    ap.add_argument("--zip", default="dist/streaming-latency-sports.zip")
    ap.add_argument("--metadata", default=".zenodo.json")
    ap.add_argument("--paths", nargs="+", default=["."],
                    help="restrict the archive to these tracked paths (e.g. the data-only "
                         "record: docs/results reproducibility)")
    ap.add_argument("--publish", action="store_true",
                    help="publish immediately instead of leaving a draft (IRREVERSIBLE)")
    ap.add_argument("--new-version", metavar="RECORD_ID", default=None,
                    help="add a new version to an existing record instead of creating a new "
                         "one, keeping its concept DOI (code 21650031, data 21650064; give "
                         "the numeric id of the LATEST version, not the concept id)")
    args = ap.parse_args(argv)

    token = os.environ.get("ZENODO_API_TOKEN")
    if not token:
        print("ZENODO_API_TOKEN is not set. Set it in your shell; do not put it in a file.")
        return 1
    if not Path(args.metadata).exists():
        print(f"Missing {args.metadata}")
        return 1

    api = SANDBOX if args.sandbox else LIVE
    bundle = build_bundle(args.zip, args.ref, paths=tuple(args.paths))
    print(f"Bundled {args.ref} -> {bundle} ({bundle.stat().st_size/1e6:.1f} MB)")

    meta = load_metadata(args.metadata)
    try:
        if args.new_version:
            dep = new_version(api, token, args.new_version)
            gone = clear_files(api, token, dep)
            if gone:
                print("Cleared inherited file(s): %s" % ", ".join(gone))
            update_metadata(api, token, dep["id"], meta)
            print("New version of record %s (concept DOI unchanged)" % args.new_version)
        else:
            dep = create_deposition(api, token, meta)
    except requests.HTTPError as e:
        code = e.response.status_code if e.response is not None else None
        if code in (401, 403):
            site = "sandbox.zenodo.org" if args.sandbox else "zenodo.org"
            print(f"{code} from {site}: the token was rejected.")
            print("Two usual causes:")
            print("  1. Wrong site. Sandbox and production have SEPARATE accounts and")
            print("     tokens; a zenodo.org token does not work on the sandbox and vice")
            print(f"     versa. Mint one at https://{site}/account/settings/applications/tokens/new/")
            print("  2. Missing scopes. The token needs 'deposit:write' (and")
            print("     'deposit:actions' only for API publishing; the browser click")
            print("     needs neither).")
            print("This script only creates a DRAFT, which you can delete, so rehearsing")
            print("on the sandbox is optional -- running against the real site is safe.")
            return 1
        raise
    upload_file(api, token, dep, bundle)
    print(f"Uploaded to draft deposition {dep['id']}")

    if args.publish:
        rec = publish(api, token, dep["id"])
        print(f"PUBLISHED. DOI: {rec.get('doi')}")
    else:
        link = dep.get("links", {}).get("html", f"{api}/deposit/depositions/{dep['id']}")
        print("Draft created but NOT published (a published record cannot be deleted).")
        print(f"Review and publish here: {link}")
        print("The DOI is issued when you publish; send it over and it goes into the paper.")
    return 0


if __name__ == "__main__":  # pragma: no cover
    import sys
    sys.exit(main())
