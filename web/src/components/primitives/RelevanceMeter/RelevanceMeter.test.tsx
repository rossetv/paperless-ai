import { render, screen } from '@testing-library/react';
import { RelevanceMeter } from './RelevanceMeter';

type RelevanceTier = 'strong' | 'good' | 'partial' | 'weak';

function filledCount(container: HTMLElement): number {
  return container.querySelectorAll('[data-filled="true"]').length;
}

describe('RelevanceMeter', () => {
  it.each<[RelevanceTier, string, number]>([
    ['strong', 'Strong match', 4],
    ['good', 'Good match', 3],
    ['partial', 'Partial match', 2],
    ['weak', 'Weak match', 1],
  ])('renders %s as "%s" with %i filled dots', (tier, label, filled) => {
    const { container } = render(<RelevanceMeter tier={tier} />);
    expect(screen.getByText(label)).toBeInTheDocument();
    expect(filledCount(container)).toBe(filled);
    // Always four dots total, whatever the tier.
    expect(container.querySelectorAll('[data-filled]')).toHaveLength(4);
  });

  it('does not render the misleading raw score', () => {
    render(<RelevanceMeter tier="strong" />);
    expect(screen.queryByText(/0\.\d/)).not.toBeInTheDocument();
    expect(screen.queryByText(/relevance ·/i)).not.toBeInTheDocument();
  });
});
