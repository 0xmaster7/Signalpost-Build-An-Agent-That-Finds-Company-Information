# Data and software licences

Current package inventory, rechecked 2026-10-17 from a fresh Python 3.12 environment after the declared `uv sync --frozen --extra m08-test` install. **50 distributions** are installed, matched to `signalpost-starter-kit/uv.lock` (SHA-256 `40d47bd127ba8673b19d03276d7aa9cd96d2a35bd04cfc226ef8f40d22506633`). This supersedes the earlier 48-row inventory, which omitted transitive distributions and included an inactive package. No dependency or licence grant was changed. The test runner is separately installed for CI and is not included in this runtime/HTTP-test-extra inventory.

| Distribution | Locked version | Declared licence metadata |
|---|---:|---|
| `annotated-doc` | `0.0.5` | MIT |
| `annotated-types` | `0.8.0` | MIT |
| `anyio` | `4.15.1` | MIT |
| `babel` | `2.18.0` | BSD-3-Clause |
| `beautifulsoup4` | `4.15.0` | MIT License |
| `certifi` | `2026.7.22` | MPL-2.0 |
| `charset-normalizer` | `3.5.1` | MIT |
| `click` | `8.5.0` | BSD-3-Clause |
| `courlan` | `1.4.0` | Apache-2.0 |
| `dateparser` | `1.4.2` | BSD-3-Clause |
| `extruct` | `0.18.0` | License :: OSI Approved :: BSD License |
| `fastapi` | `0.142.2` | MIT |
| `filelock` | `3.32.3` | MIT |
| `h11` | `0.16.0` | MIT |
| `html-text` | `0.7.1` | MIT |
| `html5lib` | `1.1` | MIT License |
| `htmldate` | `1.10.0` | Apache-2.0 |
| `httpcore` | `1.0.9` | BSD-3-Clause |
| `httpx` | `0.28.1` | BSD-3-Clause |
| `idna` | `3.19` | BSD-3-Clause |
| `jstyleson` | `0.0.2` | MIT |
| `jusText` | `3.0.2` | The BSD 2-Clause License |
| `lxml` | `6.1.2` | BSD-3-Clause |
| `lxml_html_clean` | `0.4.5` | BSD-3-Clause |
| `mf2py` | `2.0.1` | MIT |
| `opentelemetry-api` | `1.45.0` | Apache-2.0 |
| `pydantic` | `2.13.4` | MIT |
| `pydantic_core` | `2.46.4` | MIT |
| `pyparsing` | `3.3.2` | MIT |
| `pypdf` | `6.16.1` | BSD-3-Clause |
| `pyrdfa3` | `3.6.5` | License :: OSI Approved :: W3C License |
| `python-dateutil` | `2.9.0.post0` | Dual License |
| `pytz` | `2026.3.post1` | MIT |
| `rdflib` | `7.6.0` | BSD-3-Clause |
| `regex` | `2026.7.19` | Apache-2.0 AND CNRI-Python |
| `requests` | `2.34.2` | Apache-2.0 |
| `requests-file` | `3.0.1` | Apache 2.0 |
| `six` | `1.17.0` | MIT |
| `soupsieve` | `2.9.2` | MIT |
| `starlette` | `1.7.0` | BSD-3-Clause |
| `tld` | `0.13.2` | MPL-1.1 OR GPL-2.0-only OR LGPL-2.1-or-later |
| `tldextract` | `5.3.2` | BSD-3-Clause |
| `trafilatura` | `2.2.0` | Apache-2.0 |
| `typing-inspection` | `0.4.4` | MIT |
| `typing_extensions` | `4.16.0` | PSF-2.0 |
| `tzlocal` | `5.4.4` | MIT |
| `urllib3` | `2.7.0` | MIT |
| `uvicorn` | `0.54.0` | BSD-3-Clause |
| `w3lib` | `2.4.1` | BSD-3-Clause |
| `webencodings` | `0.6.1` | License :: OSI Approved :: BSD License |

Optional `crawler` and `sentiment` dependency groups are pinned in the lock but are not installed or enabled. Review upstream notices before enabling them. This inventory records installed distribution metadata, not a legal opinion. Original licence/notice files remain in each installed distribution; source archives do not redistribute installed dependency binaries.

Data acquisition, attribution and retention are documented in [`source-rights.md`](source-rights.md). Frozen organizer snapshot terms must be supplied rather than inferred. The repository has no `LICENSE` file and declares no project-code licence; third-party data/software rights do not supply one. Any new project licence is an owner decision.
