# Earlier authoritative evidence study

This folder preserves the October 31 manuscript, Overleaf package, figures, citation record and publication provenance for the authored booking, inventory and escalation experiment. The author previously submitted the VerifierShift manuscript to Preprints.org. This snapshot remains separate from the November 1 restricted-evidence public-tool replay described by the repository's current manuscript.

The unchanged experimental code remains in `pilots/strengthening/` and the original outcomes remain in `results/observed/`. From the repository root, run `python3 legacy_verify_results.py` to check all 48 logical SQL worlds and 168 recorded model requests without a model server. Run `python3 legacy_reproduce_cpu.py --out results/new_legacy_cpu` for a new logical SQL reconstruction. Historical figure inputs and images are preserved here; they are not the current typed-capsule result.
