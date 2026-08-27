"""
Script to train and serialize the champion RecoverAI recovery probability model artifact.
Fits the Calibrated Multi-Action Logistic Regression model on sim_v1/train and saves to disk.
"""

import sys
from pathlib import Path

# Ensure repo root is on sys.path
repo_root = Path(__file__).resolve().parent.parent
if str(repo_root) not in sys.path:
    sys.path.insert(0, str(repo_root))

from ml.dataset import load_split_dataset_bundle
from ml.models.bundle import create_multi_action_model


def save_champion_model(
    data_dir: Path = Path("data/sim_v1"),
    output_path: Path = Path("models/champion_recovery_model.pkl"),
) -> Path:
    """Trains and serializes the champion model artifact to disk."""
    print(f"[*] Loading training split from {data_dir / 'train'}...")
    train_bundle = load_split_dataset_bundle(data_dir, split="train")

    print("[*] Training Champion Calibrated Logistic Multi-Action Model...")
    champion_model = create_multi_action_model(
        model_type="logistic",
        calibrate=True,
        random_state=42,
    )
    champion_model.fit_all(train_bundle)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    champion_model.save(output_path)
    file_size_kb = output_path.stat().st_size / 1024.0

    print(f"[+] Champion model successfully saved to: {output_path} ({file_size_kb:.2f} KB)")
    return output_path


if __name__ == "__main__":
    save_champion_model()
