import { render, screen } from '@testing-library/react';
import { Text } from './Text';

describe('Text', () => {
  it('renders its children', () => {
    render(<Text>Hello world</Text>);
    expect(screen.getByText('Hello world')).toBeInTheDocument();
  });

  it('renders a <p> element by default', () => {
    render(<Text>Paragraph</Text>);
    expect(screen.getByText('Paragraph').tagName).toBe('P');
  });

  it('renders as the element given by the as prop', () => {
    render(<Text as="span">Inline</Text>);
    expect(screen.getByText('Inline').tagName).toBe('SPAN');
  });

  it('renders as <strong> for emphasised inline text', () => {
    render(<Text as="strong">Emphasis</Text>);
    expect(screen.getByText('Emphasis').tagName).toBe('STRONG');
  });

  it('applies the variant class', () => {
    render(<Text variant="caption">Caption text</Text>);
    expect(screen.getByText('Caption text').className).toMatch(/caption/);
  });

  it('defaults to the body variant', () => {
    render(<Text>Body text</Text>);
    expect(screen.getByText('Body text').className).toMatch(/body/);
  });

  it('sets the dateTime attribute when rendered as a time element', () => {
    render(
      <Text as="time" variant="caption" dateTime="2021-03-15">
        15 March 2021
      </Text>,
    );
    const el = screen.getByText('15 March 2021');
    expect(el.tagName).toBe('TIME');
    expect(el).toHaveAttribute('datetime', '2021-03-15');
  });

  it('does not put dateTime on a non-time element', () => {
    render(
      <Text as="span" dateTime="2021-03-15">
        Not a time
      </Text>,
    );
    expect(screen.getByText('Not a time')).not.toHaveAttribute('datetime');
  });

  it('applies a tone modifier class when tone is set', () => {
    render(<Text tone="secondary">Toned text</Text>);
    expect(screen.getByText('Toned text').className).toMatch(/tone-secondary/);
  });

  it('forwards a custom className', () => {
    render(<Text className="custom">Custom</Text>);
    expect(screen.getByText('Custom').className).toContain('custom');
  });
});
