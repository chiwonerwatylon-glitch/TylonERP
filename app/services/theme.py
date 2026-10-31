"""Tenant colour theming: derive every colour the pages need from a few hex values."""


def _channels(hex_colour):
    return tuple(int(hex_colour[i:i + 2], 16) for i in (1, 3, 5))


def mix(hex_a, hex_b, t):
    """Blend two #rrggbb colours; t=0 gives a, t=1 gives b."""
    a, b = _channels(hex_a), _channels(hex_b)
    return "#%02x%02x%02x" % tuple(round(x + (y - x) * t) for x, y in zip(a, b))


def luminance(hex_colour):
    """Perceived brightness from 0 (black) to 1 (white)."""
    r, g, b = (c / 255 for c in _channels(hex_colour))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def rgb(hex_colour):
    """'r,g,b' as used by Bootstrap's --bs-*-rgb variables."""
    return ",".join(str(c) for c in _channels(hex_colour))


def accent_css(accent):
    """CSS that recolours Bootstrap's primary in light and dark mode. Empty if no accent is set."""
    if not accent:
        return ""
    hover = mix(accent, "#000000", 0.2)
    on_primary = "#10131c" if luminance(accent) > 0.6 else "#ffffff"
    return (
        ":root,[data-bs-theme]{"
        f"--bs-primary:{accent};--bs-primary-rgb:{rgb(accent)};"
        f"--bs-link-color:{accent};--bs-link-color-rgb:{rgb(accent)};"
        f"--bs-link-hover-color:{hover};--bs-link-hover-color-rgb:{rgb(hover)};"
        f"--on-primary:{on_primary};--hero-a:{accent};--hero-b:{mix(accent, '#000000', 0.45)}"
        "}"
    )


def auth_palette(background, panel):
    """Colours for the tenant's sign-in page, or None when the tenant set neither colour."""
    if not (background or panel):
        return None
    panel = panel or background
    bg = background or panel
    light = luminance(panel) > 0.55
    return {
        "bg": bg,
        "panel": panel,
        "mode": "light" if light else "dark",
        "text": "#161b2e" if light else "#e8ecf6",
        "muted": "#5b6682" if light else "#8d99b8",
        "line": mix(panel, "#000000" if light else "#ffffff", 0.16),
        "hero_text": "#161b2e" if luminance(bg) > 0.55 else "#ffffff",
        "hero_b": mix(bg, "#000000", 0.3),
    }
