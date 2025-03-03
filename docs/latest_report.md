## InvokeCI
### InvokeCI nightly-build has not succeeded the previous **6** times.
Latest successfull run: [ Run Link ](https://github.com/duckdb/duckdb/actions/runs/13578702507)

#### Failure Details
| Conclusion   | Created at          | URL                                                       |
--------------------------------------------------------------------------------------------------
| failure      | 2025-03-03 00:36:22 | https://github.com/duckdb/duckdb/actions/runs/13620956198 |
| failure      | 2025-03-03 00:36:21 | https://github.com/duckdb/duckdb/actions/runs/13620956121 |
| failure      | 2025-03-02 00:37:13 | https://github.com/duckdb/duckdb/actions/runs/13610361539 |
| failure      | 2025-03-02 00:37:12 | https://github.com/duckdb/duckdb/actions/runs/13610361490 |
| failure      | 2025-03-01 00:37:35 | https://github.com/duckdb/duckdb/actions/runs/13599003748 |
| failure      | 2025-03-01 00:37:34 | https://github.com/duckdb/duckdb/actions/runs/13599003683 |
| failure      | 2025-02-28 00:34:36 | https://github.com/duckdb/duckdb/actions/runs/13578702457 |

#### Workflow Artifacts
| Build (Architecture)                                                        | Conclusion   | Artifact                                                                                                         | Uploaded at         |
|:----------------------------------------------------------------------------|:-------------|:-----------------------------------------------------------------------------------------------------------------|:--------------------|
| R / R Package Windows (Extensions)                                          | success      | [windows_amd64_mingw-extensions](https://github.com/duckdb/duckdb/actions/runs/13620956198/artifacts/2678794248) | 2025-03-03 02:01:08 |
| Wasm / Linux Extensions (x64) (wasm_eh)                                     | success      | [duckdb-extensions-wasm_eh](https://github.com/duckdb/duckdb/actions/runs/13620956198/artifacts/2678667348)      | 2025-03-03 01:09:06 |
| Wasm / Linux Extensions (x64) (wasm_mvp)                                    | success      | [duckdb-extensions-wasm_mvp](https://github.com/duckdb/duckdb/actions/runs/13620956198/artifacts/2678677138)     | 2025-03-03 01:13:17 |
| Wasm / Linux Extensions (x64) (wasm_threads)                                | success      | [duckdb-extensions-wasm_threads](https://github.com/duckdb/duckdb/actions/runs/13620956198/artifacts/2678678675) | 2025-03-03 01:13:56 |
| linux-release / Linux Extensions (aarch64)                                  | success      | [linux-extensions-64-aarch64](https://github.com/duckdb/duckdb/actions/runs/13620956198/artifacts/2678926414)    | 2025-03-03 02:48:57 |
| linux-release / Linux Extensions (musl + x64) (linux_amd64_musl, x64-linux) | success      | [linux-extensions-64-musl](https://github.com/duckdb/duckdb/actions/runs/13620956198/artifacts/2678851634)       | 2025-03-03 02:24:21 |
| linux-release / Linux Extensions (x64) (linux_amd64, x64-linux)             | success      | [linux-extensions-64](https://github.com/duckdb/duckdb/actions/runs/13620956198/artifacts/2678698898)            | 2025-03-03 01:23:00 |
| osx / OSX Extensions Release (arm64)                                        | success      | [duckdb-extensions-osx_arm64](https://github.com/duckdb/duckdb/actions/runs/13620956198/artifacts/2678723260)    | 2025-03-03 01:33:07 |
| osx / OSX Extensions Release (x86_64)                                       | success      | [duckdb-extensions-osx_amd64](https://github.com/duckdb/duckdb/actions/runs/13620956198/artifacts/2678742741)    | 2025-03-03 01:39:51 |
| osx / OSX Release                                                           | success      | [duckdb-binaries-osx](https://github.com/duckdb/duckdb/actions/runs/13620956198/artifacts/2678679155)            | 2025-03-03 01:14:09 |
| pyodide / Build pyodide wheel (3.10, 0.22.1, 16, 'pydantic<2')              | success      | [pyodide-python0.22.1](https://github.com/duckdb/duckdb/actions/runs/13620956198/artifacts/2678629825)           | 2025-03-03 00:53:04 |
| pyodide / Build pyodide wheel (3.11, 0.25.1, 18, 'pydantic<2')              | success      | [pyodide-python0.25.1](https://github.com/duckdb/duckdb/actions/runs/13620956198/artifacts/2678629168)           | 2025-03-03 00:52:46 |
| pyodide / Build pyodide wheel (3.12, 0.26.1, 20)                            | success      | [pyodide-python0.26.1](https://github.com/duckdb/duckdb/actions/runs/13620956198/artifacts/2678631657)           | 2025-03-03 00:53:49 |
| pyodide / Build pyodide wheel (3.12, 0.27.2, 20)                            | success      | [pyodide-python0.27.2](https://github.com/duckdb/duckdb/actions/runs/13620956198/artifacts/2678640985)           | 2025-03-03 00:57:43 |
| python / Linux Extensions (linux_amd64_gcc4) (linux_amd64_gcc4, x64-linux)  | success      | [manylinux-extensions-x64](https://github.com/duckdb/duckdb/actions/runs/13620956198/artifacts/2678757857)       | 2025-03-03 01:46:02 |
| windows / Windows (64 Bit)                                                  | success      | [duckdb-binaries-windows-amd64](https://github.com/duckdb/duckdb/actions/runs/13620956198/artifacts/2678715161)  | 2025-03-03 01:30:13 |
| windows / Windows Extensions (64-bit)                                       | success      | [windows_amd64-extensions](https://github.com/duckdb/duckdb/actions/runs/13620956198/artifacts/2679008644)       | 2025-03-03 03:15:08 |

## osx_arm64

#### Tested extensions
The following extensions could be loaded and installed successfully:
##### ['iceberg', 'mysql_scanner', 'azure', 'aws', 'postgres_scanner', 'tpch', 'spatial', 'tpcds', 'fts', 'httpfs', 'vss', 'arrow', 'sqlite_scanner', 'inet', 'excel', 'delta']
None of extensions had failed to be installed or loaded.

## osx_amd64

#### Tested extensions
The following extensions could be loaded and installed successfully:
##### ['arrow', 'httpfs', 'fts', 'vss', 'tpcds', 'delta', 'excel', 'sqlite_scanner', 'inet', 'postgres_scanner', 'iceberg', 'spatial', 'aws', 'azure', 'tpch', 'mysql_scanner']
None of extensions had failed to be installed or loaded.
