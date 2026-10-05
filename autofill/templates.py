"""Registry of photobook templates: where the PSDs live and the album page order."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]  # ...\Vinyetka

TEMPLATES = {
    "Freedom_21x30": {"psd_dir": ROOT / "Freedom_21x30" / "Photobook",
                      "pages": ["cover", "01", "02", "03", "04", "05", "06"]},
    "Flight": {"psd_dir": ROOT / "Flight" / "photobook",
               "pages": ["cover", "01", "02", "03", "04", "05", "06"]},
    "Split": {"psd_dir": ROOT / "Split" / "photobook",
              "pages": ["cover1", "cover2", "01", "02", "03", "04", "05", "06", "07", "08"]},
}
