# Ceresa Manifest Mill

A three-step workflow for ingesting image collections into the UB IIIF server and uploading them to Transkribus for transcription.

To be extended into a four- or five-step workflow (fetch and transform from Transkribus).

## Overview

This repository contains the processing pipeline for the Arcipelago Ceresa edition project, in part as rough documentation, in part as readily usable automation:

1. **[IIIF Upload](#step-1-iiif-upload)** — Preparation and ingest of digital images to the UB Bern IIIF server
2. **[IIIF Manifest Generation](#step-2-iiif-manifest-generation)** — Generate IIIF Presentation API manifests from BagIt metadata
3. **[Transkribus Upload](#step-3-issue-based-upload-to-transkribus)** — Upload collections to Transkribus for transcription

---

## Step 1: IIIF Upload

Prepare image collections using BagIt and ingest them to the IIIF server.

**Note:** Ingest is additive. New images and collections are added to the IIIF server; existing images remain accessible. If existing images should be overwritten, make sure to check the respective box in the task interface.

### Prerequisites

- Access to a staging environment with:
  - Sufficient free storage
  - `bagit.py` installed
  - The UB IIIF delivery share mounted
 
### Target structure

Input directory:

```
ceresa_A-5                      only serves as an input wrapper
ceresa_A-5/A-5                  will go to ceresa/A-5
ceresa_A-5/A-5/A-5-1_13         contents 
```

After bagging (`bagit.py` takes care of the creation of the data directory as well as manifest files):

```
ceresa_A-5                      only serves as an input wrapper
ceresa_A-5/manifest-md5.txt     IMPORTANT, SEE BELOW
ceresa_A-5/tagmanifest-md5.txt  and other bagit stuff
ceresa_A-5/data
ceresa_A-5/data/A-5             will go to ceresa/A-5 in the IIIF internal collection structure
ceresa_A-5/data/A-5/A-5-1_13    contents 
```

Check [https://en.wikipedia.org/wiki/BagIt](https://en.wikipedia.org/wiki/BagIt) for a deeper dive.

### Steps

#### Housekeeping

Prepare a staging area, either locally or directly on the delivery mount:

```bash
mkdir iiif-stage
```

Remove metadata detritus before packing:

```bash
find iiif-stage/ -type f -name '*.DS_Store' -exec rm {} \;
find iiif-stage/ -name '._*' -type f -delete
```

#### Prepare the bag

Pack the bag (replace `ceresa_A-5` with your collection name):

```bash
sudo bagit.py --contact-name 'Peter Daengeli' --md5 ceresa_A-5
```

If prepared locally, sync to delivery:

```bash
sudo rsync -r ceresa_A-5 /path-to/delivery/
```

**Important:** If working directly on delivery, collect BagIt manifests before proceeding. Bags are removed after successful ingest, and manifests will be deleted with them.

#### Run the ingest task

1. Go to [https://iiif.ub.unibe.ch/admin/task/](https://iiif.ub.unibe.ch/admin/task/)
2. Select Project "Ceresa"
3. Select the bag path
4. Start the ingest

Check for success:
- Tasks dashboard
- Email notification
- Verify the collection and test Image API requests:
  ```
  https://iiif.ub.unibe.ch/image/v3/ceresa/A-5-a_13_001.tif/info.json
  ```

#### Archive processed data

Ensure the processed input data is stored in research storage.

---

## Step 2: IIIF Manifest Generation

Generate IIIF Presentation API v3 manifests from BagIt manifests.

**Note:** Manifest generation is additive. Each issue can add new manifests or update existing ones. Previously generated manifests are preserved unless explicitly overwritten by a document with the same name.

### Steps

#### Collect BagIt manifests

SSH to the staging environment and fetch all manifests:

```bash
ssh user@staging-host 'find /path-to/iiif-stage -type d -name data -prune -o -type f -name "manifest-md5.txt" -exec cat {} +; echo' > all-manifests.txt
```

#### Open an issue

1. Go to [Issues](../../issues)
2. Click "New issue"
3. Select the "Provide BagIt Manifests for IIIF Generation" template
4. Upload or paste `all-manifests.txt` (file name is irrelevant, but contents not)
5. Submit

The workflow will process the manifests and commit any new or updated files to the repository.

#### Review results

- Check the issue reply for generation report
- Browse generated manifests at: [https://iiif.arcipelago-ceresa.digitaleditions.ch/presentation](https://iiif.arcipelago-ceresa.digitaleditions.ch/presentation)
- Individual manifests are accessible at: `https://iiif.arcipelago-ceresa.digitaleditions.ch/presentation/<document-id>.json`

---

## Step 3: Issue-based Upload to Transkribus

Upload IIIF collections to Transkribus by submitting manifest URLs.

### Steps

#### Open an issue

1. Go to [Issues](../../issues)
2. Click "New issue"
3. Select the "Upload to Transkribus" template
4. Choose target collection from dropdown
5. List IIIF manifest URLs (one per line)
6. Submit

The workflow will:
- Fetch each manifest
- Download all referenced images
- Upload as documents to the selected Transkribus collection

#### Review results

- Check the issue reply for upload report with status for each manifest
- Verify documents in your Transkribus collection

---

## Troubleshooting

### Manifest generation fails

Check the issue comment for detailed error messages. Common issues:
- Invalid BagIt manifest format
- IIIF Image API service unavailable
- Missing or incorrect file paths

Beyond that, the Action log often helps to identify problems.

### IIIF Image API returns 404

Verify:
- Ingest task completed successfully
- File exists in the expected location on the IIIF server
- File name matches exactly (case-sensitive)

### Transkribus upload fails

Check the issue comment for detailed error messages. Common issues:
- Invalid manifest URL or manifest structure
- Image download timeouts
- Transkribus API errors
- User not allowlisted (see Variables below)

---

## Repo settings

### Secrets (Settings → Secrets and variables → Actions → Secrets)

1. **`TRANSKRIBUS_CREDENTIALS`** (for Transkribus upload workflow)
   - Format: JSON string, e.g., `{"user": "user", "pw": "password"}` - make sure the string is valid JSON (certain characters might need escaping)

### Variables (Settings → Secrets and variables → Actions → Variables)

2. **`ALLOWLIST`** (for Transkribus upload workflow)
   - Format: JSON array of GitHub usernames, e.g., `["pdaengeli", "vvvyyynet"]`

### GitHub Pages (Settings → Pages)

3. **Source:** GitHub Actions (not "Deploy from a branch")
4. **Custom domain:** `iiif.arcipelago-ceresa.digitaleditions.ch`

### Repository settings

5. **Actions permissions** (Settings → Actions → General):
   - Allow GitHub Actions to create and approve pull requests: ✅ (for auto-commit)
  
### Issue labels (triggers)

6. **Create two new labels** (Issues → Labels):
     - `iiif-generation`, "IIIF manifest generation workflow (trigger)"
     - `iiif-upload`, "Transkribus upload workflow (trigger)"

---

## License

See [LICENSE](LICENSE).
