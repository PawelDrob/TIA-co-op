"""HMI device resolution from the TIA TypeIdentifier.

TypeIdentifier format (Openness manual 10/2018): OrderNumber:<MLFB>[/<firmware>][//<additional>]; an additional
part 'Portrait' means a portrait-mounted panel (width and height swapped).

Comfort Panel order numbers carry the display size as the letter after the dash and one digit
(6AV2124-0MC01-0AX0: M = 12"). Resolutions: Comfort Panels operating instructions 07/2022, section 8.8.

The declared target panel (hmi/panel.json) is the source of the resolution; the TypeIdentifier of the
hardware is the fallback before a panel is declared and the cross-check after (resolution.mismatch).
"""
import json
import re
from dataclasses import dataclass

# display size letter -> (width, height), landscape
SIZE_LETTERS = {
    'D': (480, 272),     # KP400 / KTP400 Comfort
    'G': (800, 480),     # KP700 / TP700 Comfort
    'J': (800, 480),     # KP900 / TP900 Comfort
    'M': (1280, 800),    # KP1200 / TP1200 Comfort
    'Q': (1280, 800),    # KP1500 / TP1500 Comfort
    'U': (1366, 768),    # TP1900 Comfort
    'X': (1920, 1080),   # TP2200 Comfort
}

_MLFB = re.compile(r'^6AV2(124|144)-\d([A-Z])')


@dataclass(frozen=True)
class Resolution:
    width: int
    height: int
    portrait: bool
    order_number: str        # MLFB without spaces ('' when the panel was declared by name or size)
    panel: str = ''          # panel name (TP1200 Comfort), '' when not known

    def describe(self):
        """'TP1200 Comfort (6AV2124-0MC01-0AX0), 1280 x 800' (portrait added when mounted portrait)."""
        label = ' '.join(x for x in (self.panel, '(%s)' % self.order_number if self.order_number else '') if x)
        return '%s, %d x %d%s' % (label or 'panel', self.width, self.height,
                                    ' portrait' if self.portrait else '')

    def same_screen(self, other):
        return (self.width, self.height, self.portrait) == (other.width, other.height, other.portrait)


# The Comfort Panels of the table (operating instructions 07/2022, section 8.8): name, order number, landscape size.
PANELS = [
    ('KTP400 Comfort', '6AV2124-2DC01-0AX0', 480, 272),
    ('KP400 Comfort', '6AV2124-1DC01-0AX0', 480, 272),
    ('TP700 Comfort', '6AV2124-0GC01-0AX0', 800, 480),
    ('KP700 Comfort', '6AV2124-1GC01-0AX0', 800, 480),
    ('TP900 Comfort', '6AV2124-0JC01-0AX0', 800, 480),
    ('KP900 Comfort', '6AV2124-1JC01-0AX0', 800, 480),
    ('TP1200 Comfort', '6AV2124-0MC01-0AX0', 1280, 800),
    ('KP1200 Comfort', '6AV2124-1MC01-0AX0', 1280, 800),
    ('TP1500 Comfort', '6AV2124-0QC02-0AX1', 1280, 800),
    ('KP1500 Comfort', '6AV2124-1QC02-0AX1', 1280, 800),
    ('TP1900 Comfort', '6AV2124-0UC02-0AX1', 1366, 768),
    ('TP2200 Comfort', '6AV2124-0XC02-0AX1', 1920, 1080),
]

PANEL_FILE = 'hmi/panel.json'     # one HMI device; with several, hmi/<device>/panel.json (model.Repo.panel_file)
PANEL_COMMAND = 'python -m hmipreview panel <repo> <panel name | order number | WxH> [--portrait] [--device NAME]'
_SIZE = re.compile(r'^\s*(\d+)\s*[xX]\s*(\d+)\s*$')


def panel_name(order_number):
    """Name of the panel an order number belongs to (by the part before the size letter's version digits), or ''."""
    for name, mlfb, _w, _h in PANELS:
        if order_number[:10] == mlfb[:10]:
            return name
    return ''


def panel_table():
    """The panel table as text lines, for the message that asks for a panel."""
    return '\n'.join('  %-15s %s  %d x %d' % (n, o, w, h) for n, o, w, h in PANELS)


def parse_panel(spec, portrait=False):
    """hmi/panel.json content for a panel given by name (TP1200 Comfort, TP1200), order number (6AV2 124-0MC01-0AX0,
    or a TypeIdentifier OrderNumber:...) or size (1280x800). portrait swaps a landscape size; a size given taller than
    wide is portrait already. Raises ValueError naming the accepted forms."""
    text = (spec or '').strip()
    m = _SIZE.match(text)
    if m:
        w, h = int(m.group(1)), int(m.group(2))
        if w <= 0 or h <= 0:
            raise ValueError('panel size %s: width and height must be positive' % text)
        if portrait and w > h:
            w, h = h, w
        return {'panel': '%dx%d' % (w, h), 'width': w, 'height': h, 'portrait': portrait or h > w}
    tid = text if text.startswith('OrderNumber:') else 'OrderNumber:' + text
    res = resolve(tid)
    if res is not None:
        if portrait and not res.portrait:
            res = Resolution(res.height, res.width, True, res.order_number, res.panel)
        return {'panel': res.panel or res.order_number, 'orderNumber': res.order_number,
                'width': res.width, 'height': res.height, 'portrait': res.portrait}
    key = text.lower()
    for name, _mlfb, w, h in PANELS:
        if key in (name.lower(), name.lower().replace(' comfort', '')):
            if portrait:
                w, h = h, w
            return {'panel': name, 'width': w, 'height': h, 'portrait': portrait}
    raise ValueError("Panel '%s' is not a panel name, an order number of the table or a size WxH. Panels:\n%s"
                     % (spec, panel_table()))


def panel_bytes(data):
    """hmi/panel.json content (UTF-8, keys in the order panel, orderNumber, width, height, portrait)."""
    return (json.dumps(data, indent=2) + '\n').encode('utf-8')


def panel_resolution(data):
    """Resolution of a hmi/panel.json dict, or (None, problem) when its content is not usable."""
    if not isinstance(data, dict):
        return None, 'Expected {panel, width, height, portrait}.'
    w, h, portrait = data.get('width'), data.get('height'), data.get('portrait', False)
    name, order = data.get('panel', ''), data.get('orderNumber') or ''
    if not (type(w) is int and type(h) is int and w > 0 and h > 0 and isinstance(portrait, bool)
            and isinstance(name, str) and isinstance(order, str)):
        return None, ('Expected {"panel": name, "orderNumber": optional, "width": int, "height": int, '
                      '"portrait": bool}, found %s; declare the panel again: %s' % (json.dumps(data), PANEL_COMMAND))
    return Resolution(w, h, portrait, order.replace(' ', ''), name), None



def select_type_identifier(config, device=None, folder_name=None):
    """The TypeIdentifier of the HMI device to preview, from tiabridge.json (a dict).

    hmiTypeIdentifier is a string for one HMI device, or {device: identifier} when the project has several
    (TiaBridge connect writes both). device (the device folder or name model.select_device chose) picks the entry
    whose name, or folder_name(name), it is; (None, None) when the map has none (the hardware is unknown). Without
    device, the optional key hmiDevice names the device; a map with one entry needs none. Returns (type identifier
    or None, problem or None); the problem says what to set. Never raises.
    """
    tid = config.get('hmiTypeIdentifier') if isinstance(config, dict) else None
    if not isinstance(tid, dict):
        return tid, None
    if device:
        for k, v in tid.items():
            if device == k or (folder_name is not None and device == folder_name(str(k))):
                return v, None
        return None, None
    devices = sorted(str(k) for k in tid)
    chosen = config.get('hmiDevice')
    if chosen is None and len(tid) == 1:
        return next(iter(tid.values())), None
    if isinstance(chosen, str) and chosen in tid:
        return tid[chosen], None
    listed = ', '.join(devices) or 'none'
    if chosen is None:
        return None, ("tiabridge.json lists several HMI devices (%s); set hmiDevice in tiabridge.json to the one "
                      "to preview and generate for." % listed)
    return None, ("tiabridge.json hmiDevice '%s' is not one of the HMI devices in hmiTypeIdentifier (%s); set "
                  "hmiDevice to one of them." % (chosen, listed))


def parse_type_identifier(text):
    """-> (order_number without spaces, firmware or None, additional or None), or None if not an order number."""
    if not isinstance(text, str) or not text.startswith('OrderNumber:'):
        return None
    rest = text[len('OrderNumber:'):]
    rest, _, additional = rest.partition('//')
    mlfb, _, firmware = rest.partition('/')
    return mlfb.replace(' ', ''), firmware or None, additional or None


def resolve(type_identifier):
    """Resolution for a TypeIdentifier, or None when the device is not in the table."""
    parsed = parse_type_identifier(type_identifier)
    if not parsed:
        return None
    mlfb, _fw, additional = parsed
    m = _MLFB.match(mlfb)
    if not m or m.group(2) not in SIZE_LETTERS:
        return None
    w, h = SIZE_LETTERS[m.group(2)]
    portrait = (additional or '').lower() == 'portrait'
    if portrait:
        w, h = h, w
    return Resolution(w, h, portrait, mlfb, panel_name(mlfb))
