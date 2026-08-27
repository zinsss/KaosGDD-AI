# Office Fax Bridge

The Office Fax Bridge is the narrow queue worker that converts validated PDF
jobs into HylaFAX-ready TIFF files and submits them to the office-local HylaFAX
scheduler. It runs only on Office Kaos beside the physical modem.

It is intentionally separate from the authenticated Office Fax Connector:

```text
H3 Governor
  -> authenticated Office Fax Connector
  -> versioned manifest and PDF in the shared queue
  -> Office Fax Bridge
  -> Group 3 TIFF conversion
  -> sendfax against 127.0.0.1:4559
  -> HylaFAX doneq
```

The bridge preserves the proven production workarounds:

- validate a 32-character job ID and domestic destination
- constrain the PDF path to the job directory
- verify the PDF signature and SHA-256 hash before conversion
- use Ghostscript `tiffg3` at the established fax resolution
- validate the generated TIFF with `tiffinfo`
- submit TIFF, not PDF, to avoid HylaFAX `pdf2fax.gs` path failures
- retain Nanum fonts for PDFs that do not embed Korean CID fonts
- atomically write one result and move the manifest to `processed`

HylaFAX `doneq`, not the initial `sendfax` response, remains the final sent or
failed authority. Governor performs that reconciliation through the Office Fax
Connector.

The bridge receives no Discord, Governor, database, Docker, SSH, or modem-device
credential. Its only writable mount is the shared fax queue. It reaches hfaxd
through the host network on loopback.

Run the local unit tests with:

```bash
PYTHONPATH=apps/fax-bridge/src python3 -m unittest discover -s apps/fax-bridge/tests
```

Build and run the complete Office deployment through
[`deploy/office-fax-connector`](../../deploy/office-fax-connector/README.md).
