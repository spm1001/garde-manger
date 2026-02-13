#!/usr/bin/env python3
"""Plot distribution of session full_text() lengths.

This measures what we'd actually index - the cleaned text from adapters,
not raw JSON.
"""

import sys
from pathlib import Path

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from garde.adapters.claude_code import discover_claude_code
from garde.adapters.cloud_sessions import discover_cloud_sessions
from garde.adapters.handoffs import discover_handoffs
from garde.config import load_config
import matplotlib.pyplot as plt
import numpy as np


def measure_lengths(sources, source_type: str) -> list[int]:
    """Measure full_text() length for each source."""
    lengths = []
    errors = 0
    for source in sources:
        try:
            text = source.full_text()
            lengths.append(len(text))
        except Exception as e:
            errors += 1
    if errors:
        print(f"  {source_type}: {errors} errors reading sources")
    return lengths


def main():
    print("Discovering sources...")
    config = load_config()

    # Claude Code sessions
    print("  Claude Code...")
    claude_code_sources = list(discover_claude_code(config))
    cc_lengths = measure_lengths(claude_code_sources, "claude_code")
    print(f"  Found {len(cc_lengths)} sessions")

    # Cloud sessions
    print("  Cloud sessions...")
    cloud_sources = list(discover_cloud_sessions(config))
    cloud_lengths = measure_lengths(cloud_sources, "cloud_sessions")
    print(f"  Found {len(cloud_lengths)} sessions")

    # Handoffs
    print("  Handoffs...")
    handoff_sources = list(discover_handoffs(config))
    handoff_lengths = measure_lengths(handoff_sources, "handoffs")
    print(f"  Found {len(handoff_lengths)} handoffs")

    # Combined stats
    all_lengths = cc_lengths + cloud_lengths + handoff_lengths

    print(f"\n=== Statistics ===")
    print(f"Total sources: {len(all_lengths)}")
    print(f"Total chars: {sum(all_lengths):,}")
    print(f"Mean: {np.mean(all_lengths):,.0f} chars")
    print(f"Median: {np.median(all_lengths):,.0f} chars")
    print(f"Std: {np.std(all_lengths):,.0f} chars")
    print(f"Min: {min(all_lengths):,} chars")
    print(f"Max: {max(all_lengths):,} chars")
    print(f"\nPercentiles:")
    for p in [50, 75, 90, 95, 99]:
        print(f"  {p}th: {np.percentile(all_lengths, p):,.0f} chars")

    # Estimate storage
    total_mb = sum(all_lengths) / 1_000_000
    print(f"\nEstimated FTS storage: {total_mb:.1f} MB")

    # Plot
    fig, axes = plt.subplots(2, 2, figsize=(12, 10))

    # Histogram - all sources
    ax1 = axes[0, 0]
    ax1.hist(all_lengths, bins=50, edgecolor='black', alpha=0.7)
    ax1.set_xlabel('Characters')
    ax1.set_ylabel('Count')
    ax1.set_title(f'All Sources (n={len(all_lengths)})')
    ax1.axvline(np.median(all_lengths), color='red', linestyle='--', label=f'Median: {np.median(all_lengths):,.0f}')
    ax1.legend()

    # Log scale histogram
    ax2 = axes[0, 1]
    ax2.hist(all_lengths, bins=50, edgecolor='black', alpha=0.7)
    ax2.set_xlabel('Characters')
    ax2.set_ylabel('Count (log scale)')
    ax2.set_title('All Sources (log scale)')
    ax2.set_yscale('log')

    # By source type
    ax3 = axes[1, 0]
    ax3.boxplot([cc_lengths, cloud_lengths, handoff_lengths],
                labels=['Claude Code', 'Cloud', 'Handoffs'])
    ax3.set_ylabel('Characters')
    ax3.set_title('By Source Type')
    ax3.set_yscale('log')

    # CDF
    ax4 = axes[1, 1]
    sorted_lengths = np.sort(all_lengths)
    cdf = np.arange(1, len(sorted_lengths) + 1) / len(sorted_lengths)
    ax4.plot(sorted_lengths, cdf)
    ax4.set_xlabel('Characters')
    ax4.set_ylabel('Cumulative Proportion')
    ax4.set_title('CDF - What % of sessions are under X chars?')
    ax4.axhline(0.9, color='red', linestyle='--', alpha=0.5)
    ax4.axhline(0.95, color='orange', linestyle='--', alpha=0.5)
    ax4.set_xscale('log')
    ax4.grid(True, alpha=0.3)

    plt.tight_layout()

    # Save
    output_path = Path(__file__).parent / "session_length_dist.png"
    plt.savefig(output_path, dpi=150)
    print(f"\nPlot saved to: {output_path}")

    # Also show
    plt.show()


if __name__ == "__main__":
    main()
