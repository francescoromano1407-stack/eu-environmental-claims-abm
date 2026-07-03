"""
Standalone Visualization Dashboard for the Financial Market Simulation.

This script reads daily simulation metrics from 'simulation_results.csv'
and plots the multi-panel Matplotlib dashboard.

Author: Antigravity
Date: June 2026
"""

import csv
import matplotlib.pyplot as plt


def main(csv_path="simulation_results.csv", output_path="market_simulation_dashboard.png"):
    days = []
    prices = []
    balances = []

    active_days = []
    noise_counts = []
    fund_counts = []
    chart_counts = []

    noise_wealths = []
    fund_wealths = []
    chart_wealths = []

    print(f"Reading simulation metrics from '{csv_path}'...")
    try:
        with open(csv_path, mode='r') as f:
            reader = csv.DictReader(f)
            for row in reader:
                d = int(row['day'])
                days.append(d)
                prices.append(float(row['asset_price']))
                balances.append(float(row['corporate_balance']))

                if d > 0:
                    active_days.append(d)
                    noise_counts.append(int(row['noise_count']))
                    fund_counts.append(int(row['fundamentalist_count']))
                    chart_counts.append(int(row['chartist_count']))

                    noise_wealths.append(float(row['noise_wealth']))
                    fund_wealths.append(float(row['fundamentalist_wealth']))
                    chart_wealths.append(float(row['chartist_wealth']))
    except FileNotFoundError:
        print(f"Error: '{csv_path}' not found. Please run the simulation first.")
        return

    # Use simple default style to avoid package differences
    plt.style.use('default')
    fig, (ax1, ax2, ax3) = plt.subplots(3, 1, figsize=(12, 16))

    # --- SUBPLOT 1: Asset Price vs. Corporate Balance ---
    color_price = '#1f77b4'
    ax1.plot(days, prices, color=color_price, linewidth=2, label='Asset Price ($)')
    ax1.set_xlabel('Calendar Days', fontsize=11, fontweight='bold')
    ax1.set_ylabel('Market Price ($)', color=color_price, fontsize=11, fontweight='bold')
    ax1.tick_params(axis='y', labelcolor=color_price)
    ax1.grid(True, linestyle=':', alpha=0.6)

    # Create secondary y-axis for corporate balance
    ax1_twin = ax1.twinx()
    color_bal = '#ff7f0e'
    ax1_twin.plot(days, balances, color=color_bal, linewidth=2, linestyle='--', label='Corporate Balance ($)')
    ax1_twin.set_ylabel('Corporate Balance ($)', color=color_bal, fontsize=11, fontweight='bold')
    ax1_twin.tick_params(axis='y', labelcolor=color_bal)

    # Combine legends
    lines_1, labels_1 = ax1.get_legend_handles_labels()
    lines_2, labels_2 = ax1_twin.get_legend_handles_labels()
    ax1.legend(lines_1 + lines_2, labels_1 + labels_2, loc='upper left', frameon=True, facecolor='white', framealpha=0.9)
    ax1.set_title('Asset Closing Price & Corporate Balance Sheet History', fontsize=13, fontweight='bold', pad=15)

    # --- SUBPLOT 2: Strategy Wealth Evolution ---
    colors = {'noise': '#d62728', 'fundamentalist': '#2ca02c', 'chartist': '#9467bd'}

    ax2.plot(active_days, noise_wealths, color=colors['noise'], linewidth=2.0, label='Noise Wealth')
    ax2.plot(active_days, fund_wealths, color=colors['fundamentalist'], linewidth=2.0, label='Fundamentalist Wealth')
    ax2.plot(active_days, chart_wealths, color=colors['chartist'], linewidth=2.0, label='Chartist Wealth')

    ax2.set_title('Time-Series Evolution of Average Strategy Wealth', fontsize=13, fontweight='bold', pad=15)
    ax2.set_xlabel('Calendar Days', fontsize=11, fontweight='bold')
    ax2.set_ylabel('Average Trader Wealth ($)', fontsize=11, fontweight='bold')
    ax2.grid(True, linestyle=':', alpha=0.6)
    ax2.legend(loc='upper left', frameon=True, facecolor='white', framealpha=0.9)

    # --- SUBPLOT 3: Population Demographics ---
    ax3.plot(active_days, noise_counts, color=colors['noise'], linewidth=2.0, label='Noise Count')
    ax3.plot(active_days, fund_counts, color=colors['fundamentalist'], linewidth=2.0, label='Fundamentalist Count')
    ax3.plot(active_days, chart_counts, color=colors['chartist'], linewidth=2.0, label='Chartist Count')

    ax3.set_title('Traders Population Demographics Over Time', fontsize=13, fontweight='bold', pad=15)
    ax3.set_xlabel('Calendar Days', fontsize=11, fontweight='bold')
    ax3.set_ylabel('Number of Active Agents', fontsize=11, fontweight='bold')
    ax3.grid(True, linestyle=':', alpha=0.6)
    ax3.legend(loc='upper left', frameon=True, facecolor='white', framealpha=0.9)

    plt.tight_layout()
    plt.savefig(output_path, dpi=300)
    print(f"Dashboard figure successfully saved as '{output_path}'.")
    plt.show()


if __name__ == '__main__':
    main()
