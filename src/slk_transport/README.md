# SLK transport 4.5.3

Exact role/Run/Session message contracts and the existing SLK transport commands.
This is the sole transport source; the parent build script delegates to this
prefix. The pinned `slk-overwatch-tools` dependency only supplies read helpers;
message delivery, native-start proof and engineering authority remain here.

Ordinary SLK use installs the complete prebuilt bundle. There is no per-Run
Python/pip build, source checkout or dependency download. The initial independent
repository tag `1.0.0` records the original extraction; the product is 4.5.3.

## Independent development

Python 3.10+ and setuptools 68+:

```powershell
python -m pip install .
python -I -m unittest discover -s tests -v
python -I -m slk_transport.cli --version
```

`pyproject.toml` pins the exact published OW helper Git commit. For an offline
installation, install its archived wheel first and then this tool's wheel with
`--no-index --no-deps`; this is a development/distribution route, not Run setup.

The reproducible zipapp builder takes an explicit exported OW source prefix:

```powershell
python build_zipapp.py --overwatch-tools <exact-helper-prefix> --output slk-transport.pyz
python -I slk-transport.pyz --version
```

The zipapp embeds that explicit dependency and runs without this source tree.
Managed artifacts retain the actual wheel/pyz, input hashes and build provenance.
The package's unit tests do not read real Sessions or send messages. Cross-tool,
Temporal and native delivery acceptance remain in the SLK parent regression.
