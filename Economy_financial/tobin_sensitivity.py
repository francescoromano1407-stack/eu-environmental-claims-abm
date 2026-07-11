"""
Tobin Tax Sensitivity Analysis Harness.
Runs the market simulator 101 times, scaling the Tobin Tax rate from 0% to 10%
in 0.1% increments. Dynamically overrides the module constants at runtime,
executes the daily loop, and saves the dashboard plots in a dedicated folder.
"""

import os
import sys
import shutil

# 1. Ensure the 'Economy_financial' directory is in the Python system path
# so that the 'market_sim' package can be resolved from the repository root.
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
SOURCE_ROOT = os.path.join(CURRENT_DIR, "Economy_financial")
if os.path.exists(SOURCE_ROOT):
    sys.path.insert(0, SOURCE_ROOT)
else:
    sys.path.insert(0, CURRENT_DIR)

# 2. Dynamic Imports (wrapped safely to prevent import errors)
try:
    import market_sim.constants as const
    import market_sim.simulation as sim_mod
    import market_sim.order_book as ob_mod
    from market_sim.simulation import Simulation
except ImportError as e:
    print(f"Error: Could not import 'market_sim'. Ensure you are running this "
          f"script from the root repository folder. Details: {e}")
    sys.exit(1)

# --- CONFIGURATION ---
OUTPUT_DIR = os.path.join(CURRENT_DIR, "tobin_sensitivity_results")
NUM_RUNS = 101  # 0% to 10% in 0.1% steps (0.000, 0.001, ..., 0.100)
SIM_DAYS = 500  # Default days per run (optimized for speed/accuracy balance)
SIM_TRADERS = 100  # Default trader population


def monkeypatch_tobin_rate(rate: float):
    """
    Overwrites the imported Tobin Tax reference in all active modules
    to force the entire simulation engine to run under the specific target rate.
    """
    # Override in constants
    const.TOBIN_TAX_RATE = rate
    const.MIN_TOBIN_RATE = rate  # Make it static for this specific run to isolate the effect

    # Override the local imports inside active modules
    sim_mod.TOBIN_TAX_RATE = rate
    sim_mod.MIN_TOBIN_RATE = rate
    ob_mod.TOBIN_TAX_RATE = rate


def main():
    # Prepare clean output directory
    if os.path.exists(OUTPUT_DIR):
        print(f"Cleaning existing directory: '{OUTPUT_DIR}'...")
        shutil.rmtree(OUTPUT_DIR)
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    print(f"Starting Sensitivity Analysis ({NUM_RUNS} runs)...")
    print(f"Configuration per run: {SIM_TRADERS} traders, {SIM_DAYS} days.")
    print(f"Results will be saved to: '{OUTPUT_DIR}'\n")

    for i in range(NUM_RUNS):
        # Calculate current Tobin Tax rate (e.g. 0.001 = 0.1%)
        target_rate = i * 0.001
        percentage_str = f"{target_rate * 100:.1f}%"
        
        # Apply the runtime override
        monkeypatch_tobin_rate(target_rate)

        # Progress bar
        progress = (i + 1) / NUM_RUNS
        bar_length = 30
        filled_length = int(round(bar_length * progress))
        bar = '█' * filled_length + '-' * (bar_length - filled_length)
        print(f"\r[{bar}] Run {i+1}/{NUM_RUNS} | Tobin Tax: {percentage_str:<5}", end="", flush=True)

        try:
            # Instantiate and execute
            sim = Simulation(
                num_traders=SIM_TRADERS,
                days=SIM_DAYS,
                initial_price=100.0
            )
            sim.run()

            # Save the dashboard with the specific file name
            filename = f"sim_tobin_{target_rate:.3f}.png"
            filepath = os.path.join(OUTPUT_DIR, filename)
            sim.plot_dashboard(output_path=filepath)

        except Exception as e:
            print(f"\n[ERROR] Failed during run {i+1} (Tax: {percentage_str}): {e}")
            
    print("\n\nSensitivity analysis complete.")


if __name__ == "__main__":
    main()