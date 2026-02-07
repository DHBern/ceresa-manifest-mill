#!/usr/bin/env python3
"""
Upload IIIF manifests to Transkribus

Reads issue data, fetches IIIF manifests, downloads images,
and uploads them as documents to a Transkribus collection.
"""

import json
import os
import requests
import logging
import re
import time
import random
from requests_toolbelt.multipart.encoder import MultipartEncoder
from lxml import etree

# Setup logging
OUTPUT_LOG = os.getenv('OUTPUT_LOG', './output.log')
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(OUTPUT_LOG)
    ]
)

session = None

def load_issue_data(issue_file):
    """Load parsed issue data from JSON file."""
    try:
        with open(issue_file) as f:
            data = json.load(f)
        logging.info("Issue data loaded successfully")
        return data
    except Exception as e:
        logging.error(f"Error loading issue data: {e}")
        raise

def load_credentials():
    """Load Transkribus credentials from environment."""
    try:
        creds_json = os.getenv("TRANSKRIBUS_CREDENTIALS")
        if not creds_json:
            raise ValueError("TRANSKRIBUS_CREDENTIALS not set")
        creds = json.loads(creds_json)
        logging.info("Credentials loaded successfully")
        return creds
    except Exception as e:
        logging.error(f"Error loading credentials: {e}")
        raise

def authenticate(creds):
    """Authenticate and create session with Transkribus."""
    global session
    session = requests.Session()
    try:
        response = session.post(
            'https://transkribus.eu/TrpServer/rest/auth/login',
            data=creds,
            timeout=30
        )
        response.raise_for_status()
        logging.info("✅ Authenticated with Transkribus")
    except requests.exceptions.RequestException as e:
        logging.error(f"❌ Authentication failed: {e}")
        raise

def fetch_manifest(url):
    """Fetch IIIF Presentation manifest."""
    try:
        r = requests.get(url, timeout=30)
        r.raise_for_status()
        logging.info(f"Fetched manifest: {url}")
        return r.json()
    except requests.exceptions.RequestException as e:
        logging.error(f"Error fetching manifest {url}: {e}")
        raise

def extract_pages(manifest):
    """Extract page labels and image service IDs from manifest."""
    pages = {}
    for item in manifest.get('items', []):
        try:
            label = item['label']['en'][0]
            service_id = item['items'][0]['items'][0]['body']['id']
            pages[label] = service_id
        except (KeyError, IndexError) as e:
            logging.warning(f"Could not extract page info: {e}")
            continue
    logging.info(f"Extracted {len(pages)} pages from manifest")
    return pages

def download_images(pages, wait=1):
    """Download images for all pages."""
    images = {}
    for idx, (label, service_id) in enumerate(sorted(pages.items()), 1):
        try:
            # Remove /info.json if present and construct full image URL
            base_url = service_id.rstrip('/').removesuffix('/info.json')
            image_url = f"{base_url}/full/max/0/default.jpg"
            
            r = requests.get(image_url, timeout=60, stream=True)
            r.raise_for_status()
            
            filename = f"{label}.jpg"
            images[filename] = r.content
            logging.info(f"Downloaded {filename} ({len(r.content)} bytes)")
            time.sleep(wait)
        except Exception as e:
            logging.error(f"Failed to download {label}: {e}")
            continue
    return images

def upload_file(upload_id, filename, file_data):
    """Upload a single file to Transkribus upload object."""
    try:
        mp_encoder = MultipartEncoder(
            fields={'img': (filename, file_data, 'application/octet-stream')}
        )
        response = session.put(
            f'https://transkribus.eu/TrpServer/rest/uploads/{upload_id}',
            data=mp_encoder,
            headers={'Content-Type': mp_encoder.content_type},
            timeout=120
        )
        response.raise_for_status()
        logging.info(f"✅ Uploaded {filename}")
    except Exception as e:
        logging.error(f"❌ Failed to upload {filename}: {e}")
        raise

def process_manifest(manifest_url, collection_id):
    """Process a single manifest: fetch, download, and upload."""
    logging.info(f"\n{'='*60}")
    logging.info(f"Processing: {manifest_url}")
    logging.info(f"{'='*60}")
    
    result = {
        'manifest_url': manifest_url,
        'status': 'UNKNOWN',
        'upload_obj': None,
        'error': None
    }
    
    try:
        # Fetch manifest and download images
        manifest = fetch_manifest(manifest_url)
        pages = extract_pages(manifest)
        
        if not pages:
            raise ValueError("No pages found in manifest")
        
        images = download_images(pages)
        
        if not images:
            raise ValueError("No images downloaded")
        
        # Prepare upload metadata
        doc_id = manifest_url.rstrip('/').split('/')[-1].replace('.json', '')
        pages_metadata = [
            {'fileName': filename, 'pageNr': idx}
            for idx, filename in enumerate(sorted(images.keys()), 1)
        ]
        
        upload_obj = {
            "md": {
                "title": doc_id,
                "externalId": doc_id
            },
            "pageList": {"pages": pages_metadata}
        }
        
        result['upload_obj'] = upload_obj
        
        # Create upload on Transkribus
        response = session.post(
            f'https://transkribus.eu/TrpServer/rest/uploads?collId={collection_id}',
            json=upload_obj,
            timeout=30
        )
        response.raise_for_status()
        
        response_xml = etree.fromstring(response.content)
        upload_id = response_xml.xpath('//uploadId/text()')[0]
        logging.info(f"Created upload object: {upload_id}")
        
        # Upload all files
        for filename in sorted(images.keys()):
            upload_file(upload_id, filename, images[filename])
            time.sleep(random.uniform(0.5, 2))
        
        result['status'] = 'FINISHED'
        logging.info(f"✅ FINISHED: {doc_id}")
        
    except Exception as e:
        result['status'] = 'FAILED'
        result['error'] = str(e)
        logging.error(f"❌ FAILED: {e}")
    
    return result

def clean_manifest_text(raw_text):
    """
    Clean manifest text that may be wrapped in markdown code blocks.
    
    Handles:
    - ```text\nURL\n```
    - ```\nURL\n```
    - Plain URLs
    """
    # Remove markdown code block wrappers
    cleaned = re.sub(r'^```[a-z]*\n', '', raw_text, flags=re.MULTILINE)
    cleaned = re.sub(r'\n```$', '', cleaned, flags=re.MULTILINE)
    return cleaned.strip()

def main():
    try:
        # Load issue data
        issue_file = os.getenv('ISSUE', './issue-parser-result.json')
        issue_data = load_issue_data(issue_file)
        
        # Extract manifests and collection ID
        manifests_raw = issue_data.get('iiif-manifests', issue_data.get('iiif_manifests', ''))
        
        # Clean up markdown code blocks if present
        manifests_cleaned = clean_manifest_text(manifests_raw)
        
        # Extract URLs (one per line)
        manifest_urls = [
            line.strip() 
            for line in manifests_cleaned.split('\n') 
            if line.strip() and line.strip().startswith('http')
        ]
        
        target_collection = issue_data.get('target-collection', issue_data.get('target_collection', ''))
        collection_match = re.search(r'\((\d+)\)', target_collection)
        if not collection_match:
            raise ValueError(f"Could not extract collection ID from: {target_collection}")
        collection_id = collection_match.group(1)
        
        logging.info(f"Found {len(manifest_urls)} manifest(s) to process")
        logging.info(f"Target collection ID: {collection_id}")
        
        if not manifest_urls:
            raise ValueError("No valid manifest URLs found in issue")
        
        # Authenticate
        creds = load_credentials()
        authenticate(creds)
        
        # Process each manifest
        results = []
        for url in manifest_urls:
            result = process_manifest(url, collection_id)
            results.append(result)
        
        # Summary
        logging.info(f"\n{'='*60}")
        logging.info("SUMMARY")
        logging.info(f"{'='*60}")
        
        for result in results:
            status_icon = '✅' if result['status'] == 'FINISHED' else '❌'
            logging.info(f"{status_icon} {result['manifest_url']}: {result['status']}")
            if result['error']:
                logging.info(f"   Error: {result['error']}")
        
        finished = sum(1 for r in results if r['status'] == 'FINISHED')
        failed = len(results) - finished
        logging.info(f"\nFinished: {finished}, Failed: {failed}")
        
    except Exception as e:
        logging.error(f"Workflow failed: {e}")
        raise

if __name__ == '__main__':
    main()
