"""Write draft vignette configs (configs/<tpl>.draft.json) to start hand-written configs from."""
import json
import sys
from pathlib import Path

from autofill.templates import TEMPLATES
from vignette.config import CONFIG_DIR, draft_config

HERE = Path(__file__).resolve().parent


def main(argv=None):
    CONFIG_DIR.mkdir(exist_ok=True)
    for tpl in (argv or sys.argv[1:]) or list(TEMPLATES):
        man = json.loads((HERE / "manifests" / f"{tpl}.json").read_text(encoding="utf-8"))
        out = CONFIG_DIR / f"{tpl}.draft.json"
        out.write_text(json.dumps(draft_config(man), ensure_ascii=False, indent=1), encoding="utf-8")
        print(out)


if __name__ == "__main__":
    main()
