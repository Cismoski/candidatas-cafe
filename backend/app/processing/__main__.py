"""CLI: uv run python -m app.processing IMAGEM.tif SAIDA/ [--scl SCL.tif] [--second OUTRA.tif]"""

import argparse
import json
from pathlib import Path

from .config import DEFAULT_CONFIG_PATH, load_config
from .pipeline import run_analysis


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("image", type=Path)
    ap.add_argument("out_dir", type=Path)
    ap.add_argument("--scl", type=Path)
    ap.add_argument("--second", type=Path)
    ap.add_argument("--config", type=Path, default=DEFAULT_CONFIG_PATH)
    a = ap.parse_args()
    s = run_analysis(
        a.image, a.out_dir, load_config(a.config), scl_path=a.scl, secondary_path=a.second
    )
    r = s["results"]
    print(
        json.dumps(
            {k: r[k] for k in r if k not in {"polygons", "index_stats"}},
            indent=2,
            ensure_ascii=False,
        )
    )
    print(
        "limiar dossel:",
        s["method"]["dense_canopy_ndvi_threshold"],
        s["method"]["dense_canopy_threshold_source"],
    )


if __name__ == "__main__":
    main()
