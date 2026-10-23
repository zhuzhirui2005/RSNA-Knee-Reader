# Provenance

This package extracts the reading and storage components developed in the author's RSNA Knee Abnormality Detection project:

- The report, windowing and paginated image tools originated in `scripts/serve_ai_gold_mcp.py`.
- The reversible byte codec and random-access study storage originated in `src/mcp_dicom_store.py`.
- Geometric catalog construction was separated from the competition's selection, labels and download pipeline.

The extraction replaces project-root paths with explicit CLI arguments, provides a generic catalog and synthetic data, and uses the official MCP SDK v2 instead of the earlier SDK v1 protocol bridge. It does not modify the competition server or redistribute its data.

The repository contains no Helios model code, pretrained networks, competition images, OAI data, gold labels, private tunnel executable, or account configuration. NumPy, Pillow, pydicom, Zstandard and the official MCP SDK are installed as dependencies under their own licenses.

The example annotation prompt follows the competition's public target definitions. It is a workflow example, not a claim that a particular model can diagnose every supplied study correctly. The server supplies images; inference quality depends on the chosen client, model and task.
