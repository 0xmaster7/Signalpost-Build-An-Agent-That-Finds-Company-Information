# Third-party notices

This release installs the distributions listed in [`docs/data-licenses.md`](docs/data-licenses.md), at the versions frozen in `signalpost-starter-kit/uv.lock`. Their reported licence metadata is reproduced there. The distributions are installed from PyPI and are not vendored into this repository. The installer retains each distribution's own licence/notice files in the environment. Read those files before redistributing a built bundle.

Notable multi-option declarations in the active environment include `tld` (MPL-1.1 OR GPL-2.0-only OR LGPL-2.1-or-later), `packaging` (Apache-2.0 OR BSD-2-Clause), and `regex` (Apache-2.0 AND CNRI-Python). Optional crawler/model dependencies are disabled and not part of this active inventory.

Signalpost's own code licence is undeclared in this repository.

Annual-account OCR uses installed, unmodified PyPI distributions: RapidOCR
(`rapidocr-onnxruntime`, Apache-2.0, including its bundled PP-OCR model assets),
ONNX Runtime (MIT), pypdfium2 (Apache-2.0 OR BSD-3-Clause, with PDFium third-party
notices), OpenCV (Apache-2.0), Pillow (MIT-CMU), NumPy (BSD and bundled component
notices), Shapely (BSD-3-Clause) and pyclipper (MIT). Their licence and notice
files remain in the installed distributions; no competitor code is incorporated.
Exact versions and artifact hashes are frozen in `signalpost-starter-kit/uv.lock`.
